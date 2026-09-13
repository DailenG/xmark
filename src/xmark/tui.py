from datetime import datetime
from typing import Optional
import asyncio
import webbrowser

from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical, VerticalScroll
from textual.screen import Screen
from textual.widgets import (
    Button,
    Footer,
    Header,
    Label,
    ListItem,
    ListView,
    Markdown,
    Static,
)

from xmark.api import XBookmarkClient, XAPIError
from xmark.models import BookmarkCollection, Tweet, MediaType


class BookmarkCard(Static):
    def __init__(self, bookmark_id: str, tweet: Tweet, index: int, **kwargs):
        super().__init__(**kwargs)
        self.bookmark_id = bookmark_id
        self.tweet = tweet
        self.index = index
        self.can_focus = True

    def compose(self) -> ComposeResult:
        t = self.tweet
        author = t.author
        metrics = t.public_metrics

        with Horizontal(classes="card-row"):
            initial = (author.name[:1] or author.username[:1] or "?").upper()
            yield Label(initial, classes="avatar", markup=False)
            with Vertical(classes="card-content"):
                yield Label(f"[b]{author.name}[/b] @{author.username}", classes="author")
                yield Label(t.text[:200] + ("..." if len(t.text) > 200 else ""), classes="tweet-text")
                with Horizontal(classes="metrics"):
                    yield Label(f"💬 {metrics.reply_count}", classes="metric")
                    yield Label(f"🔁 {metrics.retweet_count}", classes="metric")
                    yield Label(f"❤️ {metrics.like_count}", classes="metric")
                    yield Label(f"🔖 {metrics.bookmark_count}", classes="metric")
                if t.media:
                    with Horizontal(classes="media-preview"):
                        for m in t.media[:4]:
                            url = m.preview_image_url or m.url
                            if url:
                                yield Label(f"[🖼️ {m.type.value}]", classes="media-item")
                yield Label(t.created_at.strftime("%b %d, %Y %H:%M"), classes="timestamp")

    def on_click(self) -> None:
        self.app.push_screen(BookmarkDetailScreen(self.tweet, self.bookmark_id))


class LoadingIndicator(Static):
    def compose(self) -> ComposeResult:
        yield Label("Loading bookmarks...", classes="loading")


class ErrorView(Static):
    def __init__(self, message: str, **kwargs):
        super().__init__(**kwargs)
        self.message = message

    def compose(self) -> ComposeResult:
        yield Label(f"[red]Error: {self.message}[/red]", classes="error")
        yield Button("Retry", id="retry-btn", variant="primary")
        yield Button("Quit", id="quit-btn", variant="error")


class BookmarkListScreen(Screen):
    BINDINGS = [
        Binding("j", "cursor_down", "Down"),
        Binding("k", "cursor_up", "Up"),
        Binding("down", "cursor_down", "Down"),
        Binding("up", "cursor_up", "Up"),
        Binding("enter", "open_detail", "Open"),
        Binding("o", "open_author", "Author"),
        Binding("d", "delete_bookmark", "Delete"),
        Binding("r", "refresh", "Refresh"),
        Binding("q", "quit", "Quit"),
    ]

    def __init__(self):
        super().__init__()
        self.client: Optional[XBookmarkClient] = None
        self.collection: Optional[BookmarkCollection] = None
        self.loading_more = False

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield Container(
            VerticalScroll(
                ListView(id="bookmark-list"),
                id="list-container",
            ),
            id="main-container",
        )
        yield Footer()

    def on_mount(self) -> None:
        self.client = XBookmarkClient()
        self.load_bookmarks()

    @work(exclusive=True)
    async def load_bookmarks(self, refresh: bool = False) -> None:
        list_view = self.query_one("#bookmark-list", ListView)
        list_view.clear()
        list_view.mount(LoadingIndicator(), before=0)

        try:
            self.collection = await self.client.fetch_bookmarks(use_cache=not refresh)
            list_view.clear()
            for i, bookmark in enumerate(self.collection.bookmarks):
                tweet = self.collection.get_tweet(bookmark.tweet_id)
                if tweet:
                    list_view.append(ListItem(BookmarkCard(bookmark.id, tweet, i), id=f"bookmark-{bookmark.id}"))
            self.update_title()
        except XAPIError as e:
            list_view.clear()
            list_view.mount(ErrorView(str(e)), before=0)
        except Exception as e:
            list_view.clear()
            list_view.mount(ErrorView(f"Unexpected error: {e}"), before=0)

    @work(exclusive=True)
    async def load_more(self) -> None:
        if not self.collection or not self.collection.pagination_token or self.loading_more:
            return
        self.loading_more = True
        list_view = self.query_one("#bookmark-list", ListView)
        list_view.mount(LoadingIndicator(), before=len(list_view.children))

        try:
            more = await self.client.fetch_bookmarks(pagination_token=self.collection.pagination_token)
            list_view.children[-1].remove()  # Remove loading indicator
            for i, bookmark in enumerate(more.bookmarks):
                tweet = more.get_tweet(bookmark.tweet_id)
                if tweet:
                    idx = len(self.collection.bookmarks) + i
                    list_view.append(ListItem(BookmarkCard(bookmark.id, tweet, idx), id=f"bookmark-{bookmark.id}"))
            self.collection.bookmarks.extend(more.bookmarks)
            self.collection.tweets.update(more.tweets)
            self.collection.pagination_token = more.pagination_token
            self.update_title()
        except Exception:
            list_view.children[-1].remove()
        finally:
            self.loading_more = False

    def update_title(self) -> None:
        count = self.collection.count if self.collection else 0
        self.app.title = f"Xmark — {count} bookmarks"

    def action_cursor_down(self) -> None:
        list_view = self.query_one("#bookmark-list", ListView)
        list_view.action_cursor_down()
        if list_view.index >= len(list_view.children) - 5:
            self.load_more()

    def action_cursor_up(self) -> None:
        self.query_one("#bookmark-list", ListView).action_cursor_up()

    def action_open_detail(self) -> None:
        list_view = self.query_one("#bookmark-list", ListView)
        if list_view.highlighted_child:
            card = list_view.highlighted_child.children[0]
            if isinstance(card, BookmarkCard):
                self.app.push_screen(BookmarkDetailScreen(card.tweet, card.bookmark_id))

    def action_open_author(self) -> None:
        list_view = self.query_one("#bookmark-list", ListView)
        if list_view.highlighted_child:
            card = list_view.highlighted_child.children[0]
            if isinstance(card, BookmarkCard):
                webbrowser.open(f"https://x.com/{card.tweet.author.username}")

    @work(exclusive=True)
    async def action_delete_bookmark(self) -> None:
        list_view = self.query_one("#bookmark-list", ListView)
        if not list_view.highlighted_child:
            return
        card = list_view.highlighted_child.children[0]
        if not isinstance(card, BookmarkCard):
            return

        try:
            await self.client.delete_bookmark(card.tweet.id)
            list_view.highlighted_child.remove()
            if self.collection:
                self.collection.bookmarks = [b for b in self.collection.bookmarks if b.tweet_id != card.tweet.id]
                self.update_title()
        except XAPIError as e:
            self.app.notify(str(e), severity="error")
        except Exception as e:
            self.app.notify(f"Failed to delete: {e}", severity="error")

    def action_refresh(self) -> None:
        self.load_bookmarks(refresh=True)

    def action_quit(self) -> None:
        self.app.exit()

    @on(Button.Pressed, "#retry-btn")
    def on_retry(self) -> None:
        self.load_bookmarks(refresh=True)

    @on(Button.Pressed, "#quit-btn")
    def on_quit(self) -> None:
        self.app.exit()


class BookmarkDetailScreen(Screen):
    BINDINGS = [
        Binding("escape", "back", "Back"),
        Binding("q", "back", "Back"),
        Binding("o", "open_browser", "Open in Browser"),
        Binding("a", "open_author", "Author Profile"),
    ]

    def __init__(self, tweet: Tweet, bookmark_id: str):
        super().__init__()
        self.tweet = tweet
        self.bookmark_id = bookmark_id

    def compose(self) -> ComposeResult:
        t = self.tweet
        author = t.author
        metrics = t.public_metrics

        yield Header(show_clock=True)
        with Container(id="detail-container"):
            with VerticalScroll(id="detail-scroll"):
                with Horizontal(classes="detail-header"):
                    initial = (author.name[:1] or author.username[:1] or "?").upper()
                    yield Label(initial, classes="avatar-large", markup=False)
                    with Vertical(classes="author-info"):
                        yield Label(f"[b]{author.name}[/b] @{author.username}", classes="author-name")
                        yield Label(t.created_at.strftime("%B %d, %Y at %I:%M %p"), classes="timestamp")
                yield Label(t.text, classes="tweet-text-full", markup=True)
                if t.media:
                    with Horizontal(classes="detail-media"):
                        for m in t.media:
                            url = m.preview_image_url or m.url
                            if url:
                                yield Label(f"[link={url}][🖼️ {m.type.value}][/link]", classes="media-item")
                if t.urls:
                    with Vertical(classes="detail-urls"):
                        yield Label("Links:", classes="urls-label")
                        for url in t.urls:
                            yield Label(f"[link={url}]{url}[/link]", classes="url-item")
                with Horizontal(classes="detail-metrics"):
                    yield Label(f"💬 {metrics.reply_count} replies", classes="metric")
                    yield Label(f"🔁 {metrics.retweet_count} retweets", classes="metric")
                    yield Label(f"❤️ {metrics.like_count} likes", classes="metric")
                    yield Label(f"🔖 {metrics.bookmark_count} bookmarks", classes="metric")
            with Horizontal(classes="detail-actions"):
                yield Button("Open in Browser", id="open-browser", variant="primary")
                yield Button("Author Profile", id="open-author")
                yield Button("Back", id="back-btn", variant="default")
        yield Footer()

    def action_back(self) -> None:
        self.app.pop_screen()

    def action_open_browser(self) -> None:
        webbrowser.open(f"https://x.com/{self.tweet.author.username}/status/{self.tweet.id}")

    def action_open_author(self) -> None:
        webbrowser.open(f"https://x.com/{self.tweet.author.username}")

    @on(Button.Pressed, "#open-browser")
    def on_open_browser(self) -> None:
        self.action_open_browser()

    @on(Button.Pressed, "#open-author")
    def on_open_author(self) -> None:
        self.action_open_author()

    @on(Button.Pressed, "#back-btn")
    def on_back(self) -> None:
        self.action_back()


class XmarkApp(App):
    CSS = """
    Screen {
        background: $surface;
    }
    #main-container {
        height: 1fr;
    }
    #list-container {
        height: 1fr;
    }
    #bookmark-list {
        height: 1fr;
    }
    ListItem {
        height: auto;
        min-height: 8;
        margin: 1 2;
        border: solid $primary;
        background: $surface-lighten-1;
    }
    ListItem.-highlight {
        border: solid $accent;
        background: $accent-darken-2;
    }
    .card-row {
        height: auto;
        padding: 1;
    }
    .avatar {
        width: 4;
        height: 2;
        content-align: center middle;
        margin-right: 1;
        background: $accent-darken-1;
        color: $text;
        text-style: bold;
    }
    .avatar-large {
        width: 6;
        height: 3;
        content-align: center middle;
        margin-right: 2;
        background: $accent-darken-1;
        color: $text;
        text-style: bold;
    }
    .card-content {
        width: 1fr;
        height: auto;
    }
    .author {
        color: $text;
    }
    .tweet-text {
        color: $text-muted;
        height: auto;
    }
    .tweet-text-full {
        color: $text;
        height: auto;
        padding: 1 0;
    }
    .metrics {
        margin-top: 1;
    }
    .metric {
        color: $text-muted;
        margin-right: 2;
    }
    .media-preview {
        margin-top: 1;
    }
    .media-item {
        color: $primary;
        margin-right: 1;
    }
    .timestamp {
        color: $text-muted;
        margin-top: 1;
        text-style: dim;
    }
    .loading {
        text-align: center;
        padding: 3;
        color: $text-muted;
    }
    .error {
        text-align: center;
        padding: 3;
    }
    #detail-container {
        padding: 1 4;
        height: 1fr;
    }
    #detail-scroll {
        height: 1fr;
    }
    .detail-header {
        height: auto;
        margin-bottom: 1;
    }
    .author-info {
        width: 1fr;
    }
    .author-name {
    }
    .detail-media {
        margin: 1 0;
    }
    .detail-urls {
        margin: 1 0;
    }
    .urls-label {
        text-style: bold;
    }
    .url-item {
        color: $primary;
        margin-left: 2;
    }
    .detail-metrics {
        margin: 1 0;
        height: 1;
    }
    .detail-actions {
        dock: bottom;
        height: 3;
        padding: 1;
        background: $surface-darken-1;
    }
    """

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("ctrl+c", "quit", "Quit"),
    ]

    def __init__(self):
        super().__init__()
        self.title = "Xmark"

    def on_mount(self) -> None:
        self.push_screen(BookmarkListScreen())

    def action_quit(self) -> None:
        self.exit()


def main():
    app = XmarkApp()
    app.run()


if __name__ == "__main__":
    main()