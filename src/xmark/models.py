from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field, HttpUrl
from enum import Enum


class MediaType(str, Enum):
    PHOTO = "photo"
    VIDEO = "video"
    ANIMATED_GIF = "animated_gif"


class Media(BaseModel):
    media_key: str
    type: MediaType
    url: Optional[HttpUrl] = None
    preview_image_url: Optional[HttpUrl] = None
    alt_text: Optional[str] = None
    width: Optional[int] = None
    height: Optional[int] = None
    duration_ms: Optional[int] = None


class PublicMetrics(BaseModel):
    retweet_count: int = 0
    reply_count: int = 0
    like_count: int = 0
    quote_count: int = 0
    bookmark_count: int = 0
    impression_count: int = 0


class Author(BaseModel):
    id: str
    username: str
    name: str
    profile_image_url: Optional[HttpUrl] = None
    verified: bool = False


class Tweet(BaseModel):
    id: str
    text: str
    author: Author
    created_at: datetime
    media: list[Media] = Field(default_factory=list)
    urls: list[HttpUrl] = Field(default_factory=list)
    public_metrics: PublicMetrics = Field(default_factory=PublicMetrics)
    referenced_tweets: list[dict] = Field(default_factory=list)
    conversation_id: Optional[str] = None
    in_reply_to_user_id: Optional[str] = None


class Bookmark(BaseModel):
    id: str
    tweet_id: str
    created_at: datetime


class BookmarkCollection(BaseModel):
    bookmarks: list[Bookmark] = Field(default_factory=list)
    tweets: dict[str, Tweet] = Field(default_factory=dict)
    pagination_token: Optional[str] = None
    fetched_at: datetime = Field(default_factory=datetime.now)

    def get_tweet(self, tweet_id: str) -> Optional[Tweet]:
        return self.tweets.get(tweet_id)

    @property
    def count(self) -> int:
        return len(self.bookmarks)