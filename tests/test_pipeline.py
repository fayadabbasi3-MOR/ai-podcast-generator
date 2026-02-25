import json
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from src.pipeline import run_pipeline


# ── Fixtures ───────────────────────────────────────────


SAMPLE_CONTENT = {
    "anthropic": [
        {
            "title": "Claude Update",
            "url": "https://anthropic.com/news",
            "summary": "Big update.",
            "published": "2025-03-01T00:00:00+00:00",
            "source_name": "anthropic_blog",
            "provider": "anthropic",
            "method": "rss",
        },
    ],
    "openai": [],
    "gemini": [],
    "errors": [],
}

EMPTY_CONTENT = {
    "anthropic": [],
    "openai": [],
    "gemini": [],
    "errors": [{"source": "all_failed", "error": "timeout"}],
}

SAMPLE_SUMMARY = {
    "themes": [
        {
            "name": "Model Updates",
            "significance": 5,
            "summary": "New models released.",
            "items": [
                {
                    "title": "Claude Update",
                    "summary": "Big update.",
                    "provider": "anthropic",
                    "url": "https://anthropic.com/news",
                },
            ],
        },
    ],
    "meta": {"total_items_processed": 1, "items_after_dedup": 1, "week_ending": "2025-03-05"},
}

EMPTY_SUMMARY = {"themes": [], "meta": {}}

SAMPLE_SEGMENTS = [
    {"speaker": "interviewer", "text": "Welcome to the show."},
    {"speaker": "expert", "text": "Thanks for having me."},
    {"speaker": "interviewer", "text": "Let's discuss the news."},
    {"speaker": "expert", "text": "Sure, big week in AI."},
]


# ── Tests ──────────────────────────────────────────────


class TestRunPipeline:
    @patch("src.pipeline.ingest_all")
    def test_skips_on_zero_content(self, mock_ingest):
        """Zero items across all providers returns status 'skipped'."""
        mock_ingest.return_value = EMPTY_CONTENT

        result = run_pipeline()

        assert result["status"] == "skipped"
        assert result["themes_count"] == 0

    @patch("src.pipeline.summarize")
    @patch("src.pipeline.ingest_all")
    def test_skips_on_zero_themes(self, mock_ingest, mock_summarize):
        """Zero themes from summarize returns status 'skipped'."""
        mock_ingest.return_value = SAMPLE_CONTENT
        mock_summarize.return_value = EMPTY_SUMMARY

        result = run_pipeline()

        assert result["status"] == "skipped"
        assert result["themes_count"] == 0

    @patch("src.pipeline.generate_script")
    @patch("src.pipeline.summarize")
    @patch("src.pipeline.ingest_all")
    def test_dry_run_stops_after_script(self, mock_ingest, mock_summarize, mock_script):
        """dry_run=True stops after script generation with status 'dry_run'."""
        mock_ingest.return_value = SAMPLE_CONTENT
        mock_summarize.return_value = SAMPLE_SUMMARY
        mock_script.return_value = SAMPLE_SEGMENTS

        result = run_pipeline(dry_run=True)

        assert result["status"] == "dry_run"
        assert result["segments_count"] == 4
        assert result["themes_count"] == 1
        assert result["mp3_path"] is None

    @patch("src.pipeline.update_feed")
    @patch("src.pipeline.create_episode_item")
    @patch("src.pipeline.get_episode_metadata")
    @patch("src.pipeline.stitch_audio")
    @patch("src.pipeline.synthesize_script")
    @patch("src.pipeline.generate_script")
    @patch("src.pipeline.summarize")
    @patch("src.pipeline.ingest_all")
    def test_full_pipeline_publishes(
        self,
        mock_ingest,
        mock_summarize,
        mock_script,
        mock_tts,
        mock_stitch,
        mock_meta,
        mock_item,
        mock_feed,
        tmp_path,
    ):
        """Full pipeline run produces status 'published' with episode metadata."""
        mock_ingest.return_value = SAMPLE_CONTENT
        mock_summarize.return_value = SAMPLE_SUMMARY
        mock_script.return_value = SAMPLE_SEGMENTS
        mock_tts.return_value = [tmp_path / "seg_000.mp3", tmp_path / "seg_001.mp3"]

        # stitch_audio writes to the output path
        def fake_stitch(paths, output_path, **kwargs):
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_bytes(b"\x00" * 500_000)
            return output_path

        mock_stitch.side_effect = fake_stitch
        mock_meta.return_value = {
            "title": "AI Industry Weekly — March 5, 2025",
            "file_name": "episode_2025-03-05.mp3",
            "url": "https://example.github.io/pod/episodes/episode_2025-03-05.mp3",
            "size_bytes": 500_000,
            "duration": "00:08:32",
            "pub_date": "Wed, 05 Mar 2025 20:00:00 GMT",
            "description": "Weekly episode.",
            "guid": "episode_2025-03-05",
        }
        mock_item.return_value = MagicMock()

        result = run_pipeline()

        assert result["status"] == "published"
        assert result["episode_title"] == "AI Industry Weekly — March 5, 2025"
        assert result["duration"] == "00:08:32"
        assert result["segments_count"] == 4
        assert result["themes_count"] == 1
        mock_feed.assert_called_once()

    @patch("src.pipeline.ingest_all")
    def test_errors_propagated(self, mock_ingest):
        """Ingest errors are included in the result."""
        mock_ingest.return_value = {
            "anthropic": [
                {
                    "title": "Post",
                    "url": "https://example.com",
                    "summary": "s",
                    "published": "2025-03-01T00:00:00+00:00",
                    "source_name": "anthropic_blog",
                    "provider": "anthropic",
                    "method": "rss",
                },
            ],
            "openai": [],
            "gemini": [],
            "errors": [{"source": "openai_blog", "error": "HTTP 503"}],
        }

        # Will skip at summarize since we didn't mock it,
        # but errors should already be captured
        with patch("src.pipeline.summarize") as mock_sum:
            mock_sum.return_value = EMPTY_SUMMARY
            result = run_pipeline()

        assert len(result["errors"]) == 1
        assert result["errors"][0]["source"] == "openai_blog"
