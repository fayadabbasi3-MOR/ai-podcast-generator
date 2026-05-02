import json
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.pipeline import run_pipeline
from src.sources import ContentItem


def _content_item(msg_id: str, title: str, url: str, body: str = "x" * 1000) -> ContentItem:
    return ContentItem(
        id=msg_id,
        title=title,
        url=url,
        author="Lenny",
        published=datetime.now(timezone.utc),
        body_text=body,
        source_meta={"publication": "Lenny", "from_email": "lenny@substack.com"},
    )


def _newsletter_summary(url: str, title: str = "Build vs Buy") -> dict:
    return {
        "title": title,
        "publication": "Lenny",
        "author": "Lenny",
        "url": url,
        "one_liner": "Buy non-core, build core.",
        "summary": "x" * 100,
        "key_takeaways": ["a", "b"],
    }


def _aggregate() -> dict:
    return {
        "narrative": "x" * 250,
        "cross_cutting_themes": ["theme one"],
        "notable_quotes": ["a quote"],
    }


def _action_items(urls: list[str]) -> list[dict]:
    return [
        {
            "title": f"Action {i+1}",
            "description": "Do thing",
            "source_url": urls[i % len(urls)],
            "estimated_minutes": 20,
        }
        for i in range(3)
    ]


def _script_segments() -> list[dict]:
    return [
        {"speaker": "interviewer", "text": "Welcome back."},
        {"speaker": "expert", "text": "Glad to be here."},
        {"speaker": "interviewer", "text": "Three things to do."},
        {"speaker": "expert", "text": "Yes, audit Port templates."},
    ]


class TestSubstackDryRun:
    @patch("src.pipeline.SubstackPMSource")
    @patch("src.pipeline.summarize_one")
    @patch("src.pipeline.aggregate_summarize")
    @patch("src.pipeline.load_memory_slices")
    @patch("src.pipeline.generate_action_items")
    @patch("src.pipeline.generate_substack_script")
    def test_dry_run_with_two_items_prints_script(
        self, mock_script, mock_actions, mock_load_mem, mock_aggregate, mock_summarize_one, mock_src_cls,
        capsys,
    ):
        urls = ["https://l.com/p/1", "https://l.com/p/2"]
        items = [_content_item(f"m{i}", f"Post {i}", urls[i]) for i in range(2)]

        src_instance = MagicMock()
        src_instance.fetch.return_value = items
        mock_src_cls.return_value = src_instance

        mock_summarize_one.side_effect = [_newsletter_summary(u) for u in urls]
        mock_aggregate.return_value = _aggregate()
        mock_load_mem.return_value = {"role": "PM", "projects": "Port"}
        mock_actions.return_value = _action_items(urls)
        mock_script.return_value = _script_segments()

        result = run_pipeline(source="substack_pm", dry_run=True)

        assert result["status"] == "dry_run"
        assert result["items_count"] == 2
        assert result["segments_count"] == 4
        out = capsys.readouterr().out
        assert "[INTERVIEWER]:" in out
        assert "[EXPERT]:" in out
        # mark_processed should NOT be called in dry-run
        src_instance.mark_processed.assert_not_called()

    @patch("src.pipeline.SubstackPMSource")
    def test_zero_items_short_circuits(self, mock_src_cls):
        src_instance = MagicMock()
        src_instance.fetch.return_value = []
        mock_src_cls.return_value = src_instance

        result = run_pipeline(source="substack_pm", dry_run=True)

        assert result["status"] == "no_content"
        assert result["items_count"] == 0


class TestSubstackPublish:
    @patch("src.pipeline.SubstackPMSource")
    @patch("src.pipeline.summarize_one")
    @patch("src.pipeline.aggregate_summarize")
    @patch("src.pipeline.load_memory_slices")
    @patch("src.pipeline.generate_action_items")
    @patch("src.pipeline.generate_substack_script")
    @patch("src.pipeline.synthesize_script")
    @patch("src.pipeline.stitch_audio")
    @patch("src.pipeline.update_feed")
    @patch("src.pipeline.get_episode_metadata")
    def test_full_run_calls_mark_processed_after_publish(
        self,
        mock_get_meta, mock_update_feed, mock_stitch, mock_synth, mock_script,
        mock_actions, mock_load_mem, mock_aggregate, mock_summarize_one, mock_src_cls,
    ):
        urls = ["https://l.com/p/1"]
        src_instance = MagicMock()
        src_instance.fetch.return_value = [_content_item("m1", "Post", urls[0])]
        mock_src_cls.return_value = src_instance

        mock_summarize_one.return_value = _newsletter_summary(urls[0])
        mock_aggregate.return_value = _aggregate()
        mock_load_mem.return_value = {"role": "PM", "projects": "Port"}
        mock_actions.return_value = _action_items(urls)
        mock_script.return_value = _script_segments()
        mock_synth.return_value = [Path("/tmp/seg1.mp3")]
        mock_get_meta.return_value = {
            "title": "Substack PM Weekly — May 8, 2026",
            "url": "https://x.com/substack/episodes/episode_2026-05-08.mp3",
            "duration": "00:42:00",
            "guid": "substack_2026-05-08",
            "size_bytes": 1024,
            "pub_date": "Fri, 08 May 2026 06:00:00 GMT",
            "description": "",
            "file_name": "episode_2026-05-08.mp3",
        }

        result = run_pipeline(source="substack_pm", dry_run=False)

        assert result["status"] == "published"
        src_instance.mark_processed.assert_called_once_with()
        # update_feed must be called with channel_config (substack-specific)
        kwargs = mock_update_feed.call_args.kwargs
        assert "channel_config" in kwargs
        assert kwargs["channel_config"]["PODCAST_TITLE"] == "Substack PM Weekly"
