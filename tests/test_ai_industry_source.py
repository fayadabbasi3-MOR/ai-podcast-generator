from datetime import datetime, timezone
from hashlib import sha256
from unittest.mock import patch

from src.sources.ai_industry import AIIndustrySource


def _raw_item(title, url, provider, method="rss", days_ago=1):
    pub = datetime.now(timezone.utc).isoformat()
    return {
        "title": title,
        "url": url,
        "summary": f"Summary of {title}",
        "published": pub,
        "source_name": f"{provider}_blog",
        "provider": provider,
        "method": method,
    }


class TestAIIndustrySource:
    def test_name(self):
        assert AIIndustrySource.name == "ai_industry"

    @patch("src.sources.ai_industry.ingest_all")
    def test_fetch_returns_content_items(self, mock_ingest):
        mock_ingest.return_value = {
            "anthropic": [_raw_item("A1", "https://example.com/a1", "anthropic")],
            "openai": [_raw_item("O1", "https://example.com/o1", "openai")],
            "gemini": [],
            "errors": [],
        }
        items = AIIndustrySource().fetch(since_days=7)

        assert len(items) == 2
        for item in items:
            assert set(item.keys()) >= {
                "id", "title", "url", "author", "published", "body_text", "source_meta",
            }
            assert isinstance(item["published"], datetime)
            assert item["published"].tzinfo is not None
            assert item["body_text"] == f"Summary of {item['title']}"

    @patch("src.sources.ai_industry.ingest_all")
    def test_id_is_sha256_of_url(self, mock_ingest):
        url = "https://example.com/post"
        mock_ingest.return_value = {
            "anthropic": [_raw_item("Post", url, "anthropic")],
            "openai": [], "gemini": [], "errors": [],
        }
        items = AIIndustrySource().fetch()
        assert items[0]["id"] == sha256(url.encode("utf-8")).hexdigest()

    @patch("src.sources.ai_industry.ingest_all")
    def test_provider_carried_in_source_meta(self, mock_ingest):
        mock_ingest.return_value = {
            "anthropic": [_raw_item("A", "https://x.com/a", "anthropic")],
            "openai": [_raw_item("O", "https://x.com/o", "openai")],
            "gemini": [_raw_item("G", "https://x.com/g", "gemini")],
            "errors": [],
        }
        items = AIIndustrySource().fetch()
        providers = {it["source_meta"]["provider"] for it in items}
        assert providers == {"anthropic", "openai", "gemini"}

    @patch("src.sources.ai_industry.ingest_all")
    def test_passes_since_days_through(self, mock_ingest):
        mock_ingest.return_value = {"anthropic": [], "openai": [], "gemini": [], "errors": []}
        AIIndustrySource().fetch(since_days=14)
        mock_ingest.assert_called_once()
        assert mock_ingest.call_args.kwargs["since_days"] == 14

    @patch("src.sources.ai_industry.ingest_all")
    def test_empty_input_returns_empty_list(self, mock_ingest):
        mock_ingest.return_value = {"anthropic": [], "openai": [], "gemini": [], "errors": []}
        assert AIIndustrySource().fetch() == []
