# Xmark

Terminal application for browsing X (Twitter) bookmarks, with an Omarchy bar widget for quick access.

![Xmark TUI](docs/screenshots/tui.png)

## Features

- **Browse bookmarks** in a beautiful terminal UI (Textual)
- **View tweet details** with media previews, metrics, and links
- **Delete bookmarks** directly from the TUI
- **Omarchy bar widget** showing bookmark count with click-to-open
- **Caching** (15 min TTL) to respect X API rate limits
- **Keyboard-driven** navigation

## Installation

### Prerequisites

- Python 3.11+
- X API Bearer Token (OAuth 2.0) with `bookmark.read` scope (and `bookmark.write` for delete)
- Omarchy (for bar widget)

### Quick Install

```bash
git clone https://github.com/DailenG/xmark
cd xmark
./install.sh
```

### Manual Install

```bash
# Create virtual environment
python -m venv .venv
source .venv/bin/activate
pip install -e .

# Configure token
echo "X_BEARER_TOKEN=your_token_here" > .env

# Install Omarchy widget
cp manifest.json ~/.config/omarchy/plugins/xmark/
cp Xmark.qml ~/.config/omarchy/plugins/xmark/
omarchy plugin enable xmark
omarchy-bar restart
```

## Configuration

Create a `.env` file in the project root or set environment variable:

```bash
X_BEARER_TOKEN=your_bearer_token_here
```

Get your bearer token from the [X Developer Portal](https://developer.x.com/en/portal/dashboard).

## Usage

### TUI Application

```bash
xmark           # Launch interactive TUI
xmark --count   # Print bookmark count (for bar widget)
xmark --refresh # Force cache refresh
```

### Keybindings

| Key | Action |
|-----|--------|
| `j` / `↓` | Navigate down |
| `k` / `↑` | Navigate up |
| `Enter` | Open tweet detail |
| `o` | Open author profile in browser |
| `d` | Delete bookmark |
| `r` | Refresh bookmarks |
| `q` / `Esc` | Quit / Go back |

### Omarchy Bar Widget

- **Left-click**: Opens Xmark TUI in terminal
- **Right-click**: Menu with "Open Xmark", "Refresh", "Open X.com/bookmarks"
- **Auto-refresh**: Polls every 60 seconds
- **Notification dot**: Blue badge appears when new bookmarks since last view

## Architecture

```
src/xmark/
├── __main__.py    # CLI entry point
├── api.py         # X API v2 client (httpx)
├── models.py      # Pydantic models (Bookmark, Tweet, etc.)
└── tui.py         # Textual TUI application
```

## X API Requirements

- **Endpoint**: `GET /2/users/:id/bookmarks`
- **Scope**: `bookmark.read` (required), `bookmark.write` (for delete)
- **Rate limit**: 75 requests / 15 min per user
- **Pagination**: `pagination_token` for infinite scroll

## Development

```bash
# Run tests
pytest

# Lint
ruff check .

# Format
ruff format .
```

## License

MIT