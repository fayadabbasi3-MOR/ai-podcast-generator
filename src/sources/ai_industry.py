import logging
from datetime import datetime, timezone
from hashlib import sha256

from src.config import SOURCES
from src.ingest import ingest_all
from src.sources import ContentItem

logger = logging.getLogger(__name__)


class AIIndustrySource:
    name = "ai_industry"

    def fetch(self, since_days: int = 7) -> list[ContentItem]:
        result = ingest_all(SOURCES, since_days=since_days)
        items: list[ContentItem] = []
        for provider in ("anthropic", "openai", "gemini"):
            for raw in result.get(provider, []):
                items.append(_to_content_item(raw, provider))
        if result.get("errors"):
            logger.info("AIIndustrySource: %d source errors", len(result["errors"]))
        return items


def _to_content_item(raw: dict, provider: str) -> ContentItem:
    url = raw.get("url", "")
    return ContentItem(
        id=sha256(url.encode("utf-8")).hexdigest() if url else sha256(raw.get("title", "").encode("utf-8")).hexdigest(),
        title=raw.get("title", ""),
        url=url,
        author=None,
        published=_parse_iso(raw.get("published", "")),
        body_text=raw.get("summary", ""),
        source_meta={
            "provider": provider,
            "source_name": raw.get("source_name", ""),
            "method": raw.get("method", ""),
        },
    )


def _parse_iso(iso_str: str) -> datetime:
    if not iso_str:
        return datetime.now(timezone.utc)
    try:
        s = iso_str.replace("Z", "+00:00")
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        return datetime.now(timezone.utc)
