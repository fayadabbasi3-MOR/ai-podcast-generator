from datetime import datetime
from typing import Protocol, TypedDict


class ContentItem(TypedDict):
    id: str
    title: str
    url: str
    author: str | None
    published: datetime
    body_text: str
    source_meta: dict


class Source(Protocol):
    name: str

    def fetch(self, since_days: int = 7) -> list[ContentItem]:
        ...
