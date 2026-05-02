from unittest.mock import MagicMock, patch

import pytest

from src.scriptgen import generate_substack_script


def _ok_script() -> str:
    return (
        "[INTERVIEWER]: Welcome back to Substack PM Weekly. We've got three newsletters this week.\n"
        "[EXPERT]: Yeah, let's dive in. The first one is from Lenny on build versus buy.\n"
        "[INTERVIEWER]: What's the central claim?\n"
        "[EXPERT]: Lenny argues most teams misuse the framework, buying core capabilities and building commodity.\n"
        "[INTERVIEWER]: Three things to do this week. First, audit Port templates.\n"
        "[EXPERT]: That's the one — connects directly to the build-core principle.\n"
        "[INTERVIEWER]: Thanks for listening. Email has the links. See you next week.\n"
    )


def _mock_claude(client_cls, response_texts):
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


class TestGenerateSubstackScript:
    @patch("src.scriptgen.anthropic.Anthropic")
    def test_returns_segments_with_interviewer_first(self, anthropic_cls):
        _mock_claude(anthropic_cls, [_ok_script()])
        segments = generate_substack_script(
            per_item=[{"title": "Build vs Buy", "url": "https://l.com/p/x"}],
            aggregate={"narrative": "x" * 200, "cross_cutting_themes": [], "notable_quotes": []},
            action_items=[{"title": "Audit Port", "description": "x", "source_url": "https://l.com/p/x", "estimated_minutes": 20}],
        )
        assert segments[0]["speaker"] == "interviewer"
        speakers = {s["speaker"] for s in segments}
        assert "expert" in speakers
        assert "interviewer" in speakers

    @patch("src.scriptgen.anthropic.Anthropic")
    def test_retries_on_unparseable(self, anthropic_cls):
        _mock_claude(anthropic_cls, ["this has no tags at all", _ok_script()])
        segments = generate_substack_script(
            per_item=[{"title": "x", "url": "https://x.com"}],
            aggregate={"narrative": "x" * 200, "cross_cutting_themes": [], "notable_quotes": []},
            action_items=[],
        )
        assert len(segments) >= 4

    @patch("src.scriptgen.anthropic.Anthropic")
    def test_raises_when_expert_speaks_first(self, anthropic_cls):
        bad = (
            "[EXPERT]: I'm going first.\n"
            "[INTERVIEWER]: But you shouldn't.\n"
            "[EXPERT]: Whatever.\n"
            "[INTERVIEWER]: Fine.\n"
        )
        _mock_claude(anthropic_cls, [bad])
        with pytest.raises(ValueError, match="INTERVIEWER"):
            generate_substack_script(
                per_item=[{"title": "x", "url": "https://x.com"}],
                aggregate={"narrative": "x" * 200, "cross_cutting_themes": [], "notable_quotes": []},
                action_items=[],
            )
