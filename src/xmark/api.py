import json
import os
import time
from pathlib import Path
from typing import Optional

import httpx
from dotenv import load_dotenv

from xmark.models import Bookmark, BookmarkCollection, Media, Tweet, Author, PublicMetrics, MediaType
from xmark import auth

load_dotenv()


class XAPIError(Exception):
    def __init__(self, message: str, status_code: int = 0, retry_after: int = 0):
        super().__init__(message)
        self.status_code = status_code
        self.retry_after = retry_after


class XBookmarkClient:
    BASE_URL = "https://api.twitter.com/2"
    CACHE_DIR = Path.home() / ".cache" / "xmark"
    CACHE_FILE = CACHE_DIR / "bookmarks.json"
    COUNT_CACHE_FILE = CACHE_DIR / "count.json"
    CACHE_TTL = 15 * 60  # 15 minutes

    def __init__(self, bearer_token: Optional[str] = None):
        self._explicit_token = bearer_token
        self._client = httpx.AsyncClient(timeout=30.0)
        self._user_id: Optional[str] = None

    def _resolve_token(self) -> str:
        token = self._explicit_token or auth.get_valid_access_token() or os.getenv("X_BEARER_TOKEN")
        if not token:
            raise XAPIError(
                "Not authenticated. Run 'xmark --login' to authorize Xmark with your X account."
            )
        return token

    def _auth_headers(self) -> dict:
        return {"Authorization": f"Bearer {self._resolve_token()}"}

    async def _get_user_id(self) -> str:
        if self._user_id:
            return self._user_id
        resp = await self._client.get(f"{self.BASE_URL}/users/me", headers=self._auth_headers())
        if resp.status_code != 200:
            raise XAPIError(f"Failed to get user ID: {resp.text}", resp.status_code)
        data = resp.json()
        self._user_id = data["data"]["id"]
        return self._user_id

    def _load_cache(self) -> Optional[BookmarkCollection]:
        if not self.CACHE_FILE.exists():
            return None
        try:
            data = json.loads(self.CACHE_FILE.read_text())
            if time.time() - data.get("fetched_at", 0) > self.CACHE_TTL:
                return None
            return BookmarkCollection(**data)
        except Exception:
            return None

    def _save_cache(self, collection: BookmarkCollection) -> None:
        self.CACHE_DIR.mkdir(parents=True, exist_ok=True)
        data = collection.model_dump(mode="json")
        data["fetched_at"] = collection.fetched_at.timestamp()
        self.CACHE_FILE.write_text(json.dumps(data))

    async def fetch_bookmarks(
        self,
        max_results: int = 100,
        pagination_token: Optional[str] = None,
        use_cache: bool = True,
    ) -> BookmarkCollection:
        if use_cache:
            cached = self._load_cache()
            if cached and not pagination_token:
                return cached

        user_id = await self._get_user_id()
        params = {
            "max_results": min(max_results, 100),
            "tweet.fields": "created_at,author_id,public_metrics,referenced_tweets,conversation_id,in_reply_to_user_id,entities,attachments",
            "expansions": "author_id,attachments.media_keys,referenced_tweets.id,referenced_tweets.id.author_id",
            "media.fields": "type,url,preview_image_url,alt_text,width,height,duration_ms",
            "user.fields": "username,name,profile_image_url,verified",
        }
        if pagination_token:
            params["pagination_token"] = pagination_token

        resp = await self._client.get(
            f"{self.BASE_URL}/users/{user_id}/bookmarks",
            params=params,
            headers=self._auth_headers(),
        )

        if resp.status_code == 429:
            retry_after = int(resp.headers.get("retry-after", "900"))
            raise XAPIError("Rate limited", 429, retry_after)
        if resp.status_code != 200:
            raise XAPIError(f"Failed to fetch bookmarks: {resp.text}", resp.status_code)

        data = resp.json()
        return self._parse_bookmarks_response(data)

    def _load_count_cache(self) -> Optional[dict]:
        if not self.COUNT_CACHE_FILE.exists():
            return None
        try:
            return json.loads(self.COUNT_CACHE_FILE.read_text())
        except Exception:
            return None

    def _save_count_cache(self, count: int, top_id: Optional[str]) -> None:
        self.CACHE_DIR.mkdir(parents=True, exist_ok=True)
        self.COUNT_CACHE_FILE.write_text(
            json.dumps({"count": count, "top_id": top_id, "fetched_at": time.time()})
        )

    async def _peek_latest_bookmark_id(self) -> Optional[str]:
        """Fetch just the single newest bookmark to cheaply detect change.

        max_results=1, no expansions: $0.001 total instead of $0.001-per-bookmark
        for a full recount. X's own daily dedup makes repeat same-day peeks of
        an unchanged top bookmark free after the first.
        """
        user_id = await self._get_user_id()
        resp = await self._client.get(
            f"{self.BASE_URL}/users/{user_id}/bookmarks",
            params={"max_results": 1},
            headers=self._auth_headers(),
        )
        if resp.status_code == 429:
            retry_after = int(resp.headers.get("retry-after", "900"))
            raise XAPIError("Rate limited", 429, retry_after)
        if resp.status_code != 200:
            raise XAPIError(f"Failed to check bookmarks: {resp.text}", resp.status_code)
        data = resp.json().get("data", [])
        return data[0]["id"] if data else None

    async def _count_all_bookmarks(self) -> tuple[int, Optional[str]]:
        user_id = await self._get_user_id()
        total = 0
        top_id: Optional[str] = None
        pagination_token: Optional[str] = None
        while True:
            params = {"max_results": 100}
            if pagination_token:
                params["pagination_token"] = pagination_token
            resp = await self._client.get(
                f"{self.BASE_URL}/users/{user_id}/bookmarks",
                params=params,
                headers=self._auth_headers(),
            )
            if resp.status_code == 429:
                retry_after = int(resp.headers.get("retry-after", "900"))
                raise XAPIError("Rate limited", 429, retry_after)
            if resp.status_code != 200:
                raise XAPIError(f"Failed to fetch bookmark count: {resp.text}", resp.status_code)
            data = resp.json()
            page = data.get("data", [])
            if page and top_id is None:
                top_id = page[0]["id"]
            total += len(page)
            pagination_token = data.get("meta", {}).get("next_token")
            if not pagination_token:
                break
        return total, top_id

    async def fetch_bookmark_count(self, use_cache: bool = True) -> int:
        """Cheaply report the bookmark count, avoiding a full recount when nothing changed.

        Strategy: peek the single newest bookmark ($0.001) and compare it to the
        last known top bookmark. Unchanged -> reuse the cached count for free
        (X dedups the identical peek within the same UTC day). Changed, or no
        prior cache -> pay for one full paginated recount ($0.001/bookmark) to
        get an accurate total.

        Caveat: a bookmark removed from the middle of the list doesn't change
        the top id, so the count can undercount deletions until the next full
        sync (e.g. opening the TUI, which always does a full fetch).
        """
        cached = self._load_count_cache()
        if use_cache and cached and time.time() - cached.get("fetched_at", 0) <= self.CACHE_TTL:
            return cached["count"]

        top_id = await self._peek_latest_bookmark_id()
        if cached and top_id == cached.get("top_id"):
            self._save_count_cache(cached["count"], top_id)
            return cached["count"]

        total, top_id = await self._count_all_bookmarks()
        self._save_count_cache(total, top_id)
        return total

    async def fetch_tweet_details(self, tweet_ids: list[str]) -> dict[str, Tweet]:
        if not tweet_ids:
            return {}
        params = {
            "ids": ",".join(tweet_ids[:100]),
            "tweet.fields": "created_at,author_id,public_metrics,referenced_tweets,conversation_id,in_reply_to_user_id,entities,attachments",
            "expansions": "author_id,attachments.media_keys,referenced_tweets.id,referenced_tweets.id.author_id",
            "media.fields": "type,url,preview_image_url,alt_text,width,height,duration_ms",
            "user.fields": "username,name,profile_image_url,verified",
        }
        resp = await self._client.get(f"{self.BASE_URL}/tweets", params=params, headers=self._auth_headers())
        if resp.status_code != 200:
            raise XAPIError(f"Failed to fetch tweet details: {resp.text}", resp.status_code)

        data = resp.json()
        return self._parse_tweets(data)

    def _parse_bookmarks_response(self, data: dict) -> BookmarkCollection:
        includes = data.get("includes", {})
        users = {u["id"]: u for u in includes.get("users", [])}
        media = {m["media_key"]: m for m in includes.get("media", [])}
        tweets_data = data.get("data", [])

        tweets = {}
        bookmarks = []

        for item in tweets_data:
            tweet = self._parse_tweet(item, users, media)
            tweets[tweet.id] = tweet
            bookmarks.append(Bookmark(
                id=item["id"],
                tweet_id=item["id"],
                created_at=tweet.created_at,
            ))

        collection = BookmarkCollection(
            bookmarks=bookmarks,
            tweets=tweets,
            pagination_token=data.get("meta", {}).get("next_token"),
            fetched_at=time.time(),
        )
        self._save_cache(collection)
        return collection

    def _parse_tweets(self, data: dict) -> dict[str, Tweet]:
        includes = data.get("includes", {})
        users = {u["id"]: u for u in includes.get("users", [])}
        media = {m["media_key"]: m for m in includes.get("media", [])}
        tweets = {}
        for item in data.get("data", []):
            tweet = self._parse_tweet(item, users, media)
            tweets[tweet.id] = tweet
        return tweets

    def _parse_tweet(self, item: dict, users: dict, media: dict) -> Tweet:
        author_data = users.get(item.get("author_id"), {})
        author = Author(
            id=author_data.get("id", ""),
            username=author_data.get("username", ""),
            name=author_data.get("name", ""),
            profile_image_url=author_data.get("profile_image_url"),
            verified=author_data.get("verified", False),
        )

        tweet_media = []
        for media_key in item.get("attachments", {}).get("media_keys", []):
            m = media.get(media_key)
            if m:
                tweet_media.append(Media(
                    media_key=media_key,
                    type=MediaType(m["type"]),
                    url=m.get("url"),
                    preview_image_url=m.get("preview_image_url"),
                    alt_text=m.get("alt_text"),
                    width=m.get("width"),
                    height=m.get("height"),
                    duration_ms=m.get("duration_ms"),
                ))

        urls = []
        for url_obj in item.get("entities", {}).get("urls", []):
            if "expanded_url" in url_obj:
                urls.append(url_obj["expanded_url"])

        metrics_data = item.get("public_metrics", {})
        metrics = PublicMetrics(
            retweet_count=metrics_data.get("retweet_count", 0),
            reply_count=metrics_data.get("reply_count", 0),
            like_count=metrics_data.get("like_count", 0),
            quote_count=metrics_data.get("quote_count", 0),
            bookmark_count=metrics_data.get("bookmark_count", 0),
            impression_count=metrics_data.get("impression_count", 0),
        )

        return Tweet(
            id=item["id"],
            text=item["text"],
            author=author,
            created_at=item["created_at"],
            media=tweet_media,
            urls=urls,
            public_metrics=metrics,
            referenced_tweets=item.get("referenced_tweets", []),
            conversation_id=item.get("conversation_id"),
            in_reply_to_user_id=item.get("in_reply_to_user_id"),
        )

    async def delete_bookmark(self, tweet_id: str) -> bool:
        user_id = await self._get_user_id()
        resp = await self._client.delete(
            f"{self.BASE_URL}/users/{user_id}/bookmarks/{tweet_id}",
            headers=self._auth_headers(),
        )
        if resp.status_code == 200:
            return True
        if resp.status_code == 403:
            raise XAPIError("Token lacks write scope (bookmark.write)", 403)
        raise XAPIError(f"Failed to delete bookmark: {resp.text}", resp.status_code)

    async def close(self):
        await self._client.aclose()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        await self.close()