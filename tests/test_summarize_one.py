import json
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import anthropic
import pytest

from src.sources import ContentItem
from src.summarize import (
    aggregate_summarize,
    summarize_one,
    _validate_aggregate_summary,
    _validate_newsletter_summary,
)


def _content_item(title="Build vs Buy", publication="Lenny", url="https://l.com/p/x") -> ContentItem:
    return ContentItem(
        id="abc",
        title=title,
        url=url,
        author=publication,
        published=datetime.now(timezone.utc),
        body_text="Body text " * 100,
        source_meta={"publication": publication},
    )


def _ok_summary_json(url="https://l.com/p/x") -> str:
    return json.dumps({
        "title": "Build vs Buy",
        "publication": "Lenny",
        "author": "Lenny",
        "url": url,
        "one_liner": "Buy non-core, build core. Most teams flip it.",
        "summary": "The post argues most teams misuse the build-vs-buy framework. The author offers three diagnostic questions. Examples drawn from forty teams. Conclusion: buy non-core, build core.",
        "key_takeaways": ["Buy non-core", "Build core", "Three-question framework"],
    })


def _ok_aggregate_json() -> str:
    return json.dumps({
        "narrative": "x" * 250,
        "cross_cutting_themes": ["theme one", "theme two"],
        "notable_quotes": ["a quote"],
    })


def _mock_claude(client_cls, response_texts):
    """Return a context that mocks anthropic.Anthropic.messages.create with sequential responses."""
    client = MagicMock()
    responses = []
    for text in response_texts:
        resp = MagicMock()
        resp.content = [MagicMock(text=text)]
        resp.stop_reason = "end_turn"
        responses.append(resp)
    client.messages.create.side_effect = responses
    client_cls.return_value = client
    return client


class TestSummarizeOne:
    @patch("src.summarize.anthropic.Anthropic")
    def test_returns_valid_summary(self, anthropic_cls):
        _mock_claude(anthropic_cls, [_ok_summary_json()])
        result = summarize_one(_content_item())
        assert result["title"] == "Build vs Buy"
        assert len(result["one_liner"]) <= 140
        assert isinstance(result["key_takeaways"], list)

    @patch("src.summarize.anthropic.Anthropic")
    def test_retries_on_invalid_json(self, anthropic_cls):
        client = _mock_claude(anthropic_cls, ["not json", _ok_summary_json()])
        result = summarize_one(_content_item())
        assert result["url"] == "https://l.com/p/x"
        assert client.messages.create.call_count == 2

    @patch("src.summarize.anthropic.Anthropic")
    def test_raises_after_retry_exhausted(self, anthropic_cls):
        _mock_claude(anthropic_cls, ["not json", "still not json"])
        with pytest.raises(ValueError):
            summarize_one(_content_item())

    @patch("src.summarize.anthropic.Anthropic")
    def test_rejects_one_liner_over_200(self, anthropic_cls):
        """The validator allows up to 200 chars (loosened from 140 after smoke-test
        showed the model consistently overshooting by 1-12 chars)."""
        bad = json.dumps({
            "title": "x", "publication": "x", "author": None, "url": "https://x.com",
            "one_liner": "x" * 250,
            "summary": "x" * 30,
            "key_takeaways": [],
        })
        _mock_claude(anthropic_cls, [bad, _ok_summary_json()])
        result = summarize_one(_content_item())
        assert len(result["one_liner"]) <= 200

    @patch("src.summarize.anthropic.Anthropic")
    def test_accepts_one_liner_between_140_and_200(self, anthropic_cls):
        """The model commonly outputs 141-160 char one_liners; accept those."""
        good_long = json.dumps({
            "title": "x", "publication": "x", "author": None, "url": "https://x.com",
            "one_liner": "x" * 175,
            "summary": "x" * 30,
            "key_takeaways": ["a"],
        })
        _mock_claude(anthropic_cls, [good_long])
        result = summarize_one(_content_item())
        assert len(result["one_liner"]) == 175


class TestAggregateSummarize:
    @patch("src.summarize.anthropic.Anthropic")
    def test_returns_valid_aggregate(self, anthropic_cls):
        _mock_claude(anthropic_cls, [_ok_aggregate_json()])
        per_item = [json.loads(_ok_summary_json())]
        result = aggregate_summarize(per_item, week_ending="2026-05-08")
        assert len(result["narrative"]) >= 100
        assert isinstance(result["cross_cutting_themes"], list)

    @patch("src.summarize.anthropic.Anthropic")
    def test_retries_on_short_narrative(self, anthropic_cls):
        bad = json.dumps({"narrative": "short", "cross_cutting_themes": [], "notable_quotes": []})
        _mock_claude(anthropic_cls, [bad, _ok_aggregate_json()])
        per_item = [json.loads(_ok_summary_json())]
        result = aggregate_summarize(per_item)
        assert len(result["narrative"]) >= 100

    @patch("src.summarize.anthropic.Anthropic")
    def test_raises_after_retry_exhausted(self, anthropic_cls):
        bad = json.dumps({"narrative": "short", "cross_cutting_themes": [], "notable_quotes": []})
        _mock_claude(anthropic_cls, [bad, bad])
        with pytest.raises(ValueError):
            aggregate_summarize([json.loads(_ok_summary_json())])


class TestValidators:
    def test_newsletter_summary_requires_keys(self):
        assert not _validate_newsletter_summary({"title": "x"})

    def test_aggregate_summary_requires_narrative(self):
        assert not _validate_aggregate_summary({"narrative": "short", "cross_cutting_themes": [], "notable_quotes": []})
