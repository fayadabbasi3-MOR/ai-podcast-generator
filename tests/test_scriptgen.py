import json
from unittest.mock import patch, MagicMock

import anthropic
import pytest

from src.scriptgen import build_script_prompt, parse_script, generate_script


# ── Fixtures ───────────────────────────────────────────


SAMPLE_THEMES = {
    "themes": [
        {
            "name": "New Model Releases",
            "significance": 5,
            "summary": "Both Anthropic and OpenAI shipped new models.",
            "items": [
                {
                    "title": "Claude 4.5 Haiku Released",
                    "summary": "Faster variant.",
                    "provider": "anthropic",
                    "url": "https://anthropic.com/news/haiku",
                },
            ],
        },
    ],
    "meta": {
        "total_items_processed": 2,
        "items_after_dedup": 2,
        "week_ending": "2025-03-05",
    },
}

VALID_SCRIPT = """[INTERVIEWER]: Welcome back to AI Industry Weekly! Big week in the AI world.

[EXPERT]: Thanks for having me. Yeah, there's a lot to unpack this week.

[INTERVIEWER]: Let's start with the biggest news — new model releases. Anthropic dropped Claude 4.5 Haiku. What's the significance here?

[EXPERT]: This is a big deal. Haiku is their fast, cheap model and this update brings it much closer to the previous Sonnet in capability. It signals that the efficiency frontier is moving fast.

[INTERVIEWER]: And what does that mean for developers who are building on these APIs?

[EXPERT]: Lower costs, faster inference. If you were using Sonnet for simple tasks, you can probably drop down to Haiku now and save significantly.
"""

BAD_SCRIPT = "Here is a podcast script about AI news this week. The hosts discuss new models."


def _mock_response(text):
    content_block = MagicMock()
    content_block.text = text
    response = MagicMock()
    response.content = [content_block]
    return response


# ── parse_script ───────────────────────────────────────


class TestParseScript:
    def test_extracts_segments(self):
        """Raw text with [INTERVIEWER]: and [EXPERT]: tags parses correctly."""
        segments = parse_script(VALID_SCRIPT)

        assert len(segments) == 6
        assert all(s["speaker"] in ("interviewer", "expert") for s in segments)
        assert all(len(s["text"]) > 0 for s in segments)

    def test_rejects_too_few_segments(self):
        """Fewer than 4 segments raises ValueError."""
        short = "[INTERVIEWER]: Hello\n[EXPERT]: Hi\n"

        with pytest.raises(ValueError, match="Only 2 segments"):
            parse_script(short)

    def test_speaker_names_lowercased(self):
        """Speaker names are lowercased in output."""
        segments = parse_script(VALID_SCRIPT)

        assert segments[0]["speaker"] == "interviewer"
        assert segments[1]["speaker"] == "expert"

    def test_first_speaker_is_interviewer(self):
        """First segment speaker is always 'interviewer' (given valid input)."""
        segments = parse_script(VALID_SCRIPT)

        assert segments[0]["speaker"] == "interviewer"

    def test_handles_multiline_dialogue(self):
        """Dialogue spanning multiple lines is captured as one segment."""
        text = (
            "[INTERVIEWER]: This is a long thought\n"
            "that spans multiple lines.\n\n"
            "[EXPERT]: Short reply.\n"
            "[INTERVIEWER]: Another point.\n"
            "[EXPERT]: And another.\n"
            "[INTERVIEWER]: Wrapping up.\n"
        )

        segments = parse_script(text)

        assert segments[0]["speaker"] == "interviewer"
        assert "multiple lines" in segments[0]["text"]
        assert len(segments) == 5


# ── generate_script ────────────────────────────────────


class TestGenerateScript:
    @patch("src.scriptgen.anthropic.Anthropic")
    def test_returns_segments_on_success(self, mock_anthropic_cls):
        """Valid response is parsed into segments."""
        mock_client = MagicMock()
        mock_anthropic_cls.return_value = mock_client
        mock_client.messages.create.return_value = _mock_response(VALID_SCRIPT)

        segments = generate_script(SAMPLE_THEMES)

        assert len(segments) >= 4
        assert segments[0]["speaker"] == "interviewer"

    @patch("src.scriptgen.anthropic.Anthropic")
    def test_retries_on_bad_format(self, mock_anthropic_cls):
        """If parse_script fails, retries with format correction."""
        mock_client = MagicMock()
        mock_anthropic_cls.return_value = mock_client

        # First call returns untagged text, second returns valid script
        mock_client.messages.create.side_effect = [
            _mock_response(BAD_SCRIPT),
            _mock_response(VALID_SCRIPT),
        ]

        segments = generate_script(SAMPLE_THEMES)

        assert len(segments) >= 4
        assert mock_client.messages.create.call_count == 2
        # Verify correction message was appended
        second_call_messages = mock_client.messages.create.call_args_list[1][1]["messages"]
        assert any("[INTERVIEWER]:" in m.get("content", "") for m in second_call_messages)

    @patch("src.scriptgen.anthropic.Anthropic")
    def test_raises_on_persistent_bad_format(self, mock_anthropic_cls):
        """If both attempts produce bad format, raises ValueError."""
        mock_client = MagicMock()
        mock_anthropic_cls.return_value = mock_client
        mock_client.messages.create.return_value = _mock_response(BAD_SCRIPT)

        with pytest.raises(ValueError):
            generate_script(SAMPLE_THEMES)

    @patch("src.scriptgen.time.sleep")
    @patch("src.scriptgen.anthropic.Anthropic")
    def test_retries_on_api_error(self, mock_anthropic_cls, mock_sleep):
        """429/500/503 triggers retry with backoff."""
        mock_client = MagicMock()
        mock_anthropic_cls.return_value = mock_client

        error_503 = anthropic.APIStatusError(
            message="overloaded",
            response=MagicMock(status_code=503),
            body={"error": {"message": "overloaded"}},
        )
        mock_client.messages.create.side_effect = [
            error_503,
            _mock_response(VALID_SCRIPT),
        ]

        segments = generate_script(SAMPLE_THEMES)

        assert len(segments) >= 4
        assert mock_sleep.call_count == 1


# ── build_script_prompt ────────────────────────────────


class TestBuildScriptPrompt:
    def test_returns_json_string(self):
        """Themes dict is serialized as JSON."""
        result = build_script_prompt(SAMPLE_THEMES)

        parsed = json.loads(result)
        assert "themes" in parsed
        assert parsed["themes"][0]["name"] == "New Model Releases"
