import time
from datetime import datetime, timedelta, timezone
from unittest.mock import patch, MagicMock

import pytest
import responses

from src.ingest import (
    fetch_rss,
    fetch_atom,
    scrape_page,
    fetch_sitemap,
    fetch_anthropic_models,
    ingest_all,
)


# ── Helpers ────────────────────────────────────────────


def _make_feed_entry(title, link, days_ago=1, use_updated=False):
    """Build a mock feedparser entry with a date `days_ago` days in the past."""
    dt = datetime.now(timezone.utc) - timedelta(days=days_ago)
    tp = dt.timetuple()
    entry = MagicMock()
    entry.get = lambda k, default="": {
        "title": title,
        "link": link,
        "summary": f"Summary of {title}",
    }.get(k, default)
    entry.title = title
    entry.link = link
    entry.summary = f"Summary of {title}"
    if use_updated:
        entry.published_parsed = None
        entry.updated_parsed = tp
    else:
        entry.published_parsed = tp
        entry.updated_parsed = None
    entry.content = []
    return entry


def _make_feed(entries, bozo=False, bozo_exception=None):
    feed = MagicMock()
    feed.entries = entries
    feed.bozo = bozo
    feed.bozo_exception = bozo_exception
    return feed


# ── fetch_rss ──────────────────────────────────────────


class TestFetchRss:
    @patch("src.ingest.feedparser.parse")
    def test_filters_by_date(self, mock_parse):
        """Items older than since_days are excluded."""
        recent = _make_feed_entry("Recent", "https://example.com/recent", days_ago=2)
        old = _make_feed_entry("Old", "https://example.com/old", days_ago=30)
        mock_parse.return_value = _make_feed([recent, old])

        items = fetch_rss("https://example.com/feed.xml", since_days=7)

        assert len(items) == 1
        assert items[0]["title"] == "Recent"

    @patch("src.ingest.feedparser.parse")
    def test_returns_empty_on_failure(self, mock_parse):
        """HTTP errors return empty list, not raise."""
        mock_parse.return_value = _make_feed([], bozo=True, bozo_exception=Exception("bad"))

        items = fetch_rss("https://bad-url.com/feed.xml")

        assert items == []

    @patch("src.ingest.feedparser.parse")
    def test_returns_content_item_format(self, mock_parse):
        """Returned dicts have all ContentItem fields."""
        entry = _make_feed_entry("Title", "https://example.com/post", days_ago=1)
        mock_parse.return_value = _make_feed([entry])

        items = fetch_rss("https://example.com/feed.xml")

        assert len(items) == 1
        item = items[0]
        assert "title" in item
        assert "url" in item
        assert "summary" in item
        assert "published" in item
        assert item["method"] == "rss"


# ── fetch_atom ─────────────────────────────────────────


class TestFetchAtom:
    @patch("src.ingest.feedparser.parse")
    def test_parses_github_releases(self, mock_parse):
        """GitHub Atom feeds use <updated>, not <published>."""
        entry = _make_feed_entry(
            "v1.2.0", "https://github.com/org/repo/releases/tag/v1.2.0",
            days_ago=2, use_updated=True,
        )
        mock_parse.return_value = _make_feed([entry])

        items = fetch_atom("https://github.com/org/repo/releases.atom")

        assert len(items) == 1
        assert items[0]["title"] == "v1.2.0"
        assert items[0]["method"] == "atom"

    @patch("src.ingest.feedparser.parse")
    def test_filters_old_entries(self, mock_parse):
        """Entries older than since_days are excluded."""
        old = _make_feed_entry("Old Release", "https://example.com/old", days_ago=30, use_updated=True)
        mock_parse.return_value = _make_feed([old])

        items = fetch_atom("https://example.com/feed.atom", since_days=7)

        assert items == []


# ── scrape_page ────────────────────────────────────────


class TestScrapePage:
    @responses.activate
    def test_extracts_text(self):
        """Mock requests.get() with sample HTML, verify extraction."""
        html = """
        <html><body>
            <article>
                <h2>Release Notes</h2>
                <p>Claude 4.5 is now available.</p>
            </article>
            <div>Other stuff</div>
        </body></html>
        """
        responses.add(responses.GET, "https://example.com/notes", body=html, status=200)

        text = scrape_page("https://example.com/notes", "article")

        assert "Release Notes" in text
        assert "Claude 4.5 is now available" in text
        assert "Other stuff" not in text

    @responses.activate
    def test_raises_on_http_error(self):
        """HTTP errors propagate as exceptions."""
        responses.add(responses.GET, "https://example.com/bad", status=500)

        with pytest.raises(Exception):
            scrape_page("https://example.com/bad", "article")


# ── fetch_sitemap ──────────────────────────────────────


class TestFetchSitemap:
    @responses.activate
    def test_parses_regular_sitemap(self):
        """Regular sitemap returns {url: lastmod} dict."""
        xml = """<?xml version="1.0" encoding="UTF-8"?>
        <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
            <url>
                <loc>https://example.com/page1</loc>
                <lastmod>2025-03-01</lastmod>
            </url>
            <url>
                <loc>https://example.com/page2</loc>
            </url>
        </urlset>
        """
        responses.add(responses.GET, "https://example.com/sitemap.xml", body=xml, status=200)

        result = fetch_sitemap("https://example.com/sitemap.xml")

        assert result["https://example.com/page1"] == "2025-03-01"
        assert result["https://example.com/page2"] is None

    @responses.activate
    def test_handles_sitemap_index(self):
        """Sitemap index files trigger recursive fetch of child sitemaps."""
        index_xml = """<?xml version="1.0" encoding="UTF-8"?>
        <sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
            <sitemap><loc>https://example.com/sitemap-1.xml</loc></sitemap>
        </sitemapindex>
        """
        child_xml = """<?xml version="1.0" encoding="UTF-8"?>
        <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
            <url><loc>https://example.com/child-page</loc></url>
        </urlset>
        """
        responses.add(responses.GET, "https://example.com/sitemap.xml", body=index_xml, status=200)
        responses.add(responses.GET, "https://example.com/sitemap-1.xml", body=child_xml, status=200)

        result = fetch_sitemap("https://example.com/sitemap.xml")

        assert "https://example.com/child-page" in result


# ── fetch_anthropic_models ─────────────────────────────


class TestFetchAnthropicModels:
    @responses.activate
    def test_returns_model_list(self):
        """Returns list of model dicts with id, display_name, created_at."""
        responses.add(
            responses.GET,
            "https://api.anthropic.com/v1/models",
            json={
                "data": [
                    {"id": "claude-3-opus", "display_name": "Claude 3 Opus", "created_at": "2024-02-29"},
                    {"id": "claude-3-sonnet", "display_name": "Claude 3 Sonnet", "created_at": "2024-02-29"},
                ]
            },
            status=200,
        )

        models = fetch_anthropic_models("test-key")

        assert len(models) == 2
        assert models[0]["id"] == "claude-3-opus"
        assert models[0]["display_name"] == "Claude 3 Opus"


# ── ingest_all ─────────────────────────────────────────


class TestIngestAll:
    @patch("src.ingest.fetch_rss")
    def test_continues_on_source_failure(self, mock_fetch_rss):
        """If one source raises, others still run. Error is logged."""
        mock_fetch_rss.side_effect = [
            Exception("Network error"),  # first source fails
            [{"title": "Post", "url": "https://example.com", "summary": "s",
              "published": "2025-03-01T00:00:00+00:00",
              "source_name": "", "provider": "", "method": "rss"}],  # second succeeds
        ]

        sources = [
            {"name": "source_a", "provider": "anthropic", "url": "https://a.com/feed", "method": "rss", "enabled": True},
            {"name": "source_b", "provider": "openai", "url": "https://b.com/feed", "method": "rss", "enabled": True},
        ]

        result = ingest_all(sources)

        assert len(result["errors"]) == 1
        assert result["errors"][0]["source"] == "source_a"
        assert len(result["openai"]) == 1

    @patch("src.ingest.fetch_rss")
    @patch("src.ingest.fetch_atom")
    def test_groups_by_provider(self, mock_atom, mock_rss):
        """Output has 'anthropic', 'openai', 'gemini' keys."""
        mock_rss.return_value = [
            {"title": "A", "url": "https://a.com", "summary": "s",
             "published": "2025-03-01T00:00:00+00:00",
             "source_name": "", "provider": "", "method": "rss"},
        ]
        mock_atom.return_value = [
            {"title": "B", "url": "https://b.com", "summary": "s",
             "published": "2025-03-01T00:00:00+00:00",
             "source_name": "", "provider": "", "method": "atom"},
        ]

        sources = [
            {"name": "src_a", "provider": "anthropic", "url": "https://a.com/feed", "method": "rss", "enabled": True},
            {"name": "src_b", "provider": "gemini", "url": "https://b.com/feed.atom", "method": "atom", "enabled": True},
        ]

        result = ingest_all(sources)

        assert "anthropic" in result
        assert "openai" in result
        assert "gemini" in result
        assert len(result["anthropic"]) == 1
        assert len(result["gemini"]) == 1
        assert result["anthropic"][0]["source_name"] == "src_a"
        assert result["gemini"][0]["source_name"] == "src_b"

    def test_skips_disabled_sources(self):
        """Disabled sources are not fetched."""
        sources = [
            {"name": "disabled_src", "provider": "openai", "url": "https://x.com/feed", "method": "rss", "enabled": False},
        ]

        result = ingest_all(sources)

        assert result["openai"] == []
        assert result["errors"] == []
