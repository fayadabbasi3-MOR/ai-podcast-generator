import json
from unittest.mock import patch, MagicMock

import anthropic
import pytest

from src.summarize import build_summarize_prompt, summarize, _try_parse_json, _validate_summarize_output


# ── Fixtures ───────────────────────────────────────────


SAMPLE_CONTENT = {
    "anthropic": [
        {
            "title": "Claude 4.5 Haiku Released",
            "url": "https://anthropic.com/news/haiku",
            "summary": "Faster, cheaper model variant.",
            "published": "2025-03-01T00:00:00+00:00",
            "source_name": "anthropic_blog",
            "provider": "anthropic",
            "method": "rss",
        },
    ],
    "openai": [
        {
            "title": "GPT-5 Preview",
            "url": "https://openai.com/blog/gpt5",
            "summary": "New flagship model.",
            "published": "2025-03-02T00:00:00+00:00",
            "source_name": "openai_blog",
            "provider": "openai",
            "method": "rss",
        },
    ],
    "gemini": [],
    "errors": [],
}

VALID_SUMMARIZE_RESPONSE = json.dumps({
    "themes": [
        {
            "name": "New Model Releases",
            "significance": 5,
            "summary": "Both Anthropic and OpenAI shipped new models.",
            "items": [
                {
                    "title": "Claude 4.5 Haiku Released",
                    "summary": "Anthropic released a faster variant.",
                    "provider": "anthropic",
                    "url": "https://anthropic.com/news/haiku",
                },
                {
                    "title": "GPT-5 Preview",
                    "summary": "OpenAI previewed GPT-5.",
                    "provider": "openai",
                    "url": "https://openai.com/blog/gpt5",
                },
            ],
        },
    ],
    "meta": {
        "total_items_processed": 2,
        "items_after_dedup": 2,
        "week_ending": "2025-03-05",
    },
})


def _mock_response(text):
    """Build a mock Claude API response with the given text."""
    content_block = MagicMock()
    content_block.text = text
    response = MagicMock()
    response.content = [content_block]
    return response


# ── build_summarize_prompt ─────────────────────────────


class TestBuildSummarizePrompt:
    def test_formats_content_by_provider(self):
        """User message groups items by provider."""
        prompt = build_summarize_prompt(SAMPLE_CONTENT)

        assert "ANTHROPIC" in prompt
        assert "OPENAI" in prompt
        assert "Claude 4.5 Haiku Released" in prompt
        assert "GPT-5 Preview" in prompt

    def test_skips_empty_providers(self):
        """Providers with no items are not included."""
        prompt = build_summarize_prompt(SAMPLE_CONTENT)

        assert "GEMINI" not in prompt

    def test_includes_errors(self):
        """Error section is included when errors exist."""
        content = {**SAMPLE_CONTENT, "errors": [{"source": "bad_src", "error": "timeout"}]}
        prompt = build_summarize_prompt(content)

        assert "ERRORS" in prompt
        assert "bad_src" in prompt


# ── summarize ──────────────────────────────────────────


class TestSummarize:
    @patch("src.summarize.anthropic.Anthropic")
    def test_returns_valid_structure(self, mock_anthropic_cls):
        """Output has 'themes' list and 'meta' dict."""
        mock_client = MagicMock()
        mock_anthropic_cls.return_value = mock_client
        mock_client.messages.create.return_value = _mock_response(VALID_SUMMARIZE_RESPONSE)

        result = summarize(SAMPLE_CONTENT)

        assert "themes" in result
        assert isinstance(result["themes"], list)
        assert len(result["themes"]) >= 1
        assert "meta" in result

    @patch("src.summarize.anthropic.Anthropic")
    def test_retries_on_invalid_json(self, mock_anthropic_cls):
        """If first response isn't JSON, retries with correction message."""
        mock_client = MagicMock()
        mock_anthropic_cls.return_value = mock_client

        # First call returns garbage, second returns valid JSON
        mock_client.messages.create.side_effect = [
            _mock_response("Here are the themes: not json"),
            _mock_response(VALID_SUMMARIZE_RESPONSE),
        ]

        result = summarize(SAMPLE_CONTENT)

        assert "themes" in result
        # Two calls: original + retry with correction
        assert mock_client.messages.create.call_count == 2
        # The retry message list should include the correction
        second_call_messages = mock_client.messages.create.call_args_list[1][1]["messages"]
        assert any("valid JSON" in m.get("content", "") for m in second_call_messages)

    @patch("src.summarize.time.sleep")
    @patch("src.summarize.anthropic.Anthropic")
    def test_retries_on_api_error(self, mock_anthropic_cls, mock_sleep):
        """429/500/503 triggers retry with backoff."""
        mock_client = MagicMock()
        mock_anthropic_cls.return_value = mock_client

        # First two calls raise 429, third succeeds
        error_429 = anthropic.APIStatusError(
            message="rate limited",
            response=MagicMock(status_code=429),
            body={"error": {"message": "rate limited"}},
        )
        mock_client.messages.create.side_effect = [
            error_429,
            error_429,
            _mock_response(VALID_SUMMARIZE_RESPONSE),
        ]

        result = summarize(SAMPLE_CONTENT)

        assert "themes" in result
        assert mock_sleep.call_count == 2  # slept before retry 2 and 3

    @patch("src.summarize.anthropic.Anthropic")
    def test_raises_after_all_retries_exhausted(self, mock_anthropic_cls):
        """Hard fail if all API retries exhausted."""
        mock_client = MagicMock()
        mock_anthropic_cls.return_value = mock_client

        error_500 = anthropic.APIStatusError(
            message="internal error",
            response=MagicMock(status_code=500),
            body={"error": {"message": "internal error"}},
        )
        mock_client.messages.create.side_effect = error_500

        with pytest.raises(anthropic.APIStatusError):
            summarize(SAMPLE_CONTENT)

    @patch("src.summarize.anthropic.Anthropic")
    def test_raises_on_persistent_invalid_json(self, mock_anthropic_cls):
        """If both attempts produce invalid JSON, raises ValueError."""
        mock_client = MagicMock()
        mock_anthropic_cls.return_value = mock_client

        mock_client.messages.create.return_value = _mock_response("still not json")

        with pytest.raises(ValueError, match="Summarize failed"):
            summarize(SAMPLE_CONTENT)

    @patch("src.summarize.anthropic.Anthropic")
    def test_handles_markdown_fenced_json(self, mock_anthropic_cls):
        """JSON wrapped in ```json fences is still parsed correctly."""
        mock_client = MagicMock()
        mock_anthropic_cls.return_value = mock_client

        fenced = f"```json\n{VALID_SUMMARIZE_RESPONSE}\n```"
        mock_client.messages.create.return_value = _mock_response(fenced)

        result = summarize(SAMPLE_CONTENT)

        assert "themes" in result


# ── helpers ────────────────────────────────────────────


class TestHelpers:
    def test_try_parse_json_valid(self):
        assert _try_parse_json('{"a": 1}') == {"a": 1}

    def test_try_parse_json_invalid(self):
        assert _try_parse_json("not json") is None

    def test_try_parse_json_strips_fences(self):
        result = _try_parse_json('```json\n{"a": 1}\n```')
        assert result == {"a": 1}

    def test_validate_requires_themes_list(self):
        assert _validate_summarize_output({"themes": [{"name": "x"}]}) is True
        assert _validate_summarize_output({"themes": []}) is False
        assert _validate_summarize_output({"no_themes": True}) is False
        assert _validate_summarize_output("string") is False
