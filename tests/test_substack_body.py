from pathlib import Path

import pytest

from src.sources._substack_body import (
    BodyTooShort,
    extract_post,
    _find_canonical_url,
    _strip_chrome_lines,
)
from bs4 import BeautifulSoup


FIXTURE = Path(__file__).parent / "fixtures" / "substack_sample.html"


class TestExtractPost:
    def test_returns_canonical_url_and_text(self):
        html = FIXTURE.read_text()
        url, text = extract_post(html)
        assert url == "https://lennysnewsletter.substack.com/p/build-vs-buy-trap"
        assert len(text) > 500
        assert "Build vs. Buy" in text or "build-vs-buy" in text.lower() or "build" in text.lower()

    def test_strips_unsubscribe_lines(self):
        html = FIXTURE.read_text()
        _, text = extract_post(html)
        assert "Unsubscribe" not in text
        assert "Manage your subscription" not in text

    def test_raises_on_short_body(self):
        with pytest.raises(BodyTooShort):
            extract_post("<html><body><p>too short</p></body></html>")

    def test_raises_on_empty_html(self):
        with pytest.raises(BodyTooShort):
            extract_post("")


class TestFindCanonicalUrl:
    def test_prefers_link_canonical(self):
        html = '<html><head><link rel="canonical" href="https://example.com/post"/></head></html>'
        soup = BeautifulSoup(html, "lxml")
        assert _find_canonical_url(soup, html) == "https://example.com/post"

    def test_falls_back_to_og_url(self):
        html = '<html><head><meta property="og:url" content="https://example.com/og"/></head></html>'
        soup = BeautifulSoup(html, "lxml")
        assert _find_canonical_url(soup, html) == "https://example.com/og"

    def test_falls_back_to_substack_pattern(self):
        html = '<html><body><a href="https://lenny.substack.com/p/some-slug">x</a></body></html>'
        soup = BeautifulSoup(html, "lxml")
        url = _find_canonical_url(soup, html)
        assert url == "https://lenny.substack.com/p/some-slug"

    def test_returns_empty_when_none_found(self):
        html = "<html><body>nothing here</body></html>"
        soup = BeautifulSoup(html, "lxml")
        assert _find_canonical_url(soup, html) == ""


class TestStripChromeLines:
    def test_removes_unsubscribe(self):
        text = "Real content line\nUnsubscribe from this list\nMore content"
        cleaned = _strip_chrome_lines(text)
        assert "Real content line" in cleaned
        assert "More content" in cleaned
        assert "Unsubscribe" not in cleaned

    def test_drops_empty_lines(self):
        assert _strip_chrome_lines("a\n\n\nb") == "a\nb"
