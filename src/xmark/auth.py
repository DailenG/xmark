import base64
import hashlib
import json
import os
import secrets
import time
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from threading import Thread
from typing import Optional

import httpx
from dotenv import load_dotenv

load_dotenv()

AUTHORIZE_URL = "https://twitter.com/i/oauth2/authorize"
TOKEN_URL = "https://api.twitter.com/2/oauth2/token"
DEFAULT_SCOPES = "bookmark.read bookmark.write tweet.read users.read offline.access"

TOKEN_FILE = Path.home() / ".cache" / "xmark" / "tokens.json"
TOKEN_EXPIRY_MARGIN = 60  # seconds


class AuthError(Exception):
    pass


class TokenStore:
    def __init__(self, path: Path = TOKEN_FILE):
        self.path = path

    def load(self) -> Optional[dict]:
        if not self.path.exists():
            return None
        try:
            return json.loads(self.path.read_text())
        except Exception:
            return None

    def save(self, data: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(data))
        self.path.chmod(0o600)

    def clear(self) -> None:
        if self.path.exists():
            self.path.unlink()


def _generate_pkce_pair() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode()).digest()
    challenge = base64.urlsafe_b64encode(digest).decode().rstrip("=")
    return verifier, challenge


class _CallbackHandler(BaseHTTPRequestHandler):
    result: dict = {}

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        params = urllib.parse.parse_qs(parsed.query)
        _CallbackHandler.result["code"] = params.get("code", [None])[0]
        _CallbackHandler.result["state"] = params.get("state", [None])[0]
        _CallbackHandler.result["error"] = params.get("error", [None])[0]
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        if _CallbackHandler.result.get("code"):
            body = "<html><body><h2>Xmark authorized — you can close this tab.</h2></body></html>"
        else:
            body = f"<html><body><h2>Authorization failed: {_CallbackHandler.result.get('error')}</h2></body></html>"
        self.wfile.write(body.encode())

    def log_message(self, format, *args):
        pass


def _client_id() -> str:
    client_id = os.getenv("X_CLIENT_ID")
    if not client_id:
        raise AuthError("X_CLIENT_ID not set in .env — create an OAuth 2.0 Native App at developer.x.com")
    return client_id


def _redirect_uri() -> str:
    return os.getenv("X_CLIENT_REDIRECT", "http://127.0.0.1:8080/callback")


def _exchange_code(code: str, verifier: str, client_id: str, redirect_uri: str) -> dict:
    resp = httpx.post(
        TOKEN_URL,
        data={
            "code": code,
            "grant_type": "authorization_code",
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "code_verifier": verifier,
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    if resp.status_code != 200:
        raise AuthError(f"Token exchange failed: {resp.text}")
    return resp.json()


def login(scopes: str = DEFAULT_SCOPES, timeout: int = 120) -> dict:
    """Run the OAuth 2.0 Authorization Code + PKCE flow end-to-end.

    Starts a local callback server on the configured redirect URI, opens the
    system browser to X's consent screen, waits for the redirect, exchanges
    the code for tokens (no client secret — this is a public/native client),
    and persists the result to the token store.
    """
    client_id = _client_id()
    redirect_uri = _redirect_uri()
    parsed_redirect = urllib.parse.urlparse(redirect_uri)
    port = parsed_redirect.port or 8080
    host = parsed_redirect.hostname or "127.0.0.1"

    verifier, challenge = _generate_pkce_pair()
    state = secrets.token_urlsafe(16)

    _CallbackHandler.result = {}
    server = HTTPServer((host, port), _CallbackHandler)

    auth_url = (
        f"{AUTHORIZE_URL}?response_type=code&client_id={urllib.parse.quote(client_id)}"
        f"&redirect_uri={urllib.parse.quote(redirect_uri, safe='')}"
        f"&scope={urllib.parse.quote(scopes)}"
        f"&state={state}"
        f"&code_challenge={challenge}&code_challenge_method=S256"
    )

    thread = Thread(target=server.handle_request, daemon=True)
    thread.start()

    webbrowser.open(auth_url)

    thread.join(timeout=timeout)
    server.server_close()

    result = _CallbackHandler.result
    if not result.get("code"):
        raise AuthError(f"Authorization failed or timed out: {result.get('error', 'no callback received')}")
    if result.get("state") != state:
        raise AuthError("OAuth state mismatch — possible CSRF, aborting")

    token_data = _exchange_code(result["code"], verifier, client_id, redirect_uri)
    token_data["obtained_at"] = time.time()
    TokenStore().save(token_data)
    return token_data


def _refresh(refresh_token: str, client_id: str) -> dict:
    resp = httpx.post(
        TOKEN_URL,
        data={
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": client_id,
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    if resp.status_code != 200:
        raise AuthError(f"Token refresh failed: {resp.text}")
    token_data = resp.json()
    token_data["obtained_at"] = time.time()
    if "refresh_token" not in token_data:
        token_data["refresh_token"] = refresh_token
    TokenStore().save(token_data)
    return token_data


def get_valid_access_token() -> Optional[str]:
    """Returns a valid access token, refreshing via the stored refresh token if expired.

    Returns None if no token exists or refresh fails — caller should prompt for `xmark --login`.
    """
    store = TokenStore()
    data = store.load()
    if not data or "access_token" not in data:
        return None

    expires_at = data.get("obtained_at", 0) + data.get("expires_in", 7200)
    if time.time() < expires_at - TOKEN_EXPIRY_MARGIN:
        return data["access_token"]

    refresh_token = data.get("refresh_token")
    if not refresh_token:
        return None
    try:
        client_id = _client_id()
        token_data = _refresh(refresh_token, client_id)
        return token_data["access_token"]
    except AuthError:
        return None