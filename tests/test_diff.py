import json
from unittest.mock import patch, MagicMock

import pytest

from src.diff import (
    load_previous_snapshot,
    save_snapshot,
    diff_scrape,
    diff_sitemap,
    diff_models,
)


# ── load_previous_snapshot ─────────────────────────────


class TestLoadPreviousSnapshot:
    @patch("src.diff.subprocess.run")
    def test_returns_none_on_missing(self, mock_run):
        """If snapshots branch doesn't exist, return None."""
        mock_run.return_value = MagicMock(returncode=128, stdout="", stderr="fatal: not a git repo")

        result = load_previous_snapshot("anthropic_blog")

        assert result is None

    @patch("src.diff.subprocess.run")
    def test_returns_parsed_json(self, mock_run):
        """If snapshot exists, returns parsed JSON dict."""
        snapshot = {"fetched_at": "2025-03-01T00:00:00+00:00", "content_hash": "abc123", "raw_text": "hello"}
        mock_run.return_value = MagicMock(returncode=0, stdout=json.dumps(snapshot))

        result = load_previous_snapshot("anthropic_release_notes")

        assert result == snapshot

    @patch("src.diff.subprocess.run")
    def test_returns_none_on_invalid_json(self, mock_run):
        """If git returns non-JSON content, return None."""
        mock_run.return_value = MagicMock(returncode=0, stdout="not valid json {{{")

        result = load_previous_snapshot("bad_source")

        assert result is None


# ── save_snapshot ──────────────────────────────────────


class TestSaveSnapshot:
    def test_writes_json_file(self, tmp_path):
        """Snapshot is written as formatted JSON."""
        with patch("src.diff.SNAPSHOTS_DIR", tmp_path):
            data = {"fetched_at": "2025-03-01T00:00:00+00:00", "models": []}
            save_snapshot("anthropic_models", data)

            path = tmp_path / "anthropic_models.json"
            assert path.exists()
            assert json.loads(path.read_text()) == data


# ── diff_scrape ────────────────────────────────────────


class TestDiffScrape:
    @patch("src.diff.save_snapshot")
    @patch("src.diff.load_previous_snapshot")
    def test_detects_change(self, mock_load, mock_save):
        """Different content_hash means content changed."""
        mock_load.return_value = {
            "fetched_at": "2025-03-01T00:00:00+00:00",
            "content_hash": "old_hash_value",
            "raw_text": "old content",
        }

        result = diff_scrape("anthropic_release_notes", "new content here")

        assert result == "new content here"
        mock_save.assert_called_once()

    @patch("src.diff.save_snapshot")
    @patch("src.diff.load_previous_snapshot")
    def test_returns_none_when_unchanged(self, mock_load, mock_save):
        """Same content_hash means no change."""
        import hashlib
        text = "unchanged content"
        content_hash = hashlib.sha256(text.encode()).hexdigest()

        mock_load.return_value = {
            "fetched_at": "2025-03-01T00:00:00+00:00",
            "content_hash": content_hash,
            "raw_text": text,
        }

        result = diff_scrape("anthropic_release_notes", text)

        assert result is None
        mock_save.assert_called_once()

    @patch("src.diff.save_snapshot")
    @patch("src.diff.load_previous_snapshot")
    def test_first_run_returns_all_text(self, mock_load, mock_save):
        """No previous snapshot — returns everything as new."""
        mock_load.return_value = None

        result = diff_scrape("new_source", "brand new content")

        assert result == "brand new content"


# ── diff_sitemap ───────────────────────────────────────


class TestDiffSitemap:
    @patch("src.diff.save_snapshot")
    @patch("src.diff.load_previous_snapshot")
    def test_finds_new_urls(self, mock_load, mock_save):
        """URLs in current but not in previous are returned."""
        mock_load.return_value = {
            "fetched_at": "2025-03-01T00:00:00+00:00",
            "urls": {
                "https://example.com/page1": "2025-02-01",
            },
        }

        current = {
            "https://example.com/page1": "2025-02-01",
            "https://example.com/page2": "2025-03-01",
            "https://example.com/page3": None,
        }

        result = diff_sitemap("openai_release_sitemap", current)

        assert "https://example.com/page2" in result
        assert "https://example.com/page3" in result
        assert "https://example.com/page1" not in result

    @patch("src.diff.save_snapshot")
    @patch("src.diff.load_previous_snapshot")
    def test_detects_lastmod_changes(self, mock_load, mock_save):
        """URLs whose lastmod changed are also returned."""
        mock_load.return_value = {
            "fetched_at": "2025-03-01T00:00:00+00:00",
            "urls": {
                "https://example.com/page1": "2025-02-01",
            },
        }

        current = {
            "https://example.com/page1": "2025-03-05",  # lastmod changed
        }

        result = diff_sitemap("test_sitemap", current)

        assert "https://example.com/page1" in result

    @patch("src.diff.save_snapshot")
    @patch("src.diff.load_previous_snapshot")
    def test_first_run_returns_all_urls(self, mock_load, mock_save):
        """No previous snapshot — all URLs are new."""
        mock_load.return_value = None

        current = {
            "https://example.com/a": None,
            "https://example.com/b": "2025-03-01",
        }

        result = diff_sitemap("new_sitemap", current)

        assert len(result) == 2


# ── diff_models ────────────────────────────────────────


class TestDiffModels:
    @patch("src.diff.save_snapshot")
    @patch("src.diff.load_previous_snapshot")
    def test_finds_new_models(self, mock_load, mock_save):
        """Model IDs present now but not before are returned."""
        mock_load.return_value = {
            "fetched_at": "2025-03-01T00:00:00+00:00",
            "models": [
                {"id": "claude-3-opus", "display_name": "Claude 3 Opus", "created_at": "2024-02-29"},
            ],
        }

        current = [
            {"id": "claude-3-opus", "display_name": "Claude 3 Opus", "created_at": "2024-02-29"},
            {"id": "claude-4-sonnet", "display_name": "Claude 4 Sonnet", "created_at": "2025-03-01"},
        ]

        result = diff_models("anthropic_models", current)

        assert len(result) == 1
        assert result[0]["id"] == "claude-4-sonnet"

    @patch("src.diff.save_snapshot")
    @patch("src.diff.load_previous_snapshot")
    def test_first_run_returns_all_models(self, mock_load, mock_save):
        """No previous snapshot — all models are new."""
        mock_load.return_value = None

        current = [
            {"id": "claude-3-opus", "display_name": "Claude 3 Opus", "created_at": "2024-02-29"},
        ]

        result = diff_models("anthropic_models", current)

        assert len(result) == 1

    @patch("src.diff.save_snapshot")
    @patch("src.diff.load_previous_snapshot")
    def test_no_new_models(self, mock_load, mock_save):
        """If all models already existed, returns empty list."""
        mock_load.return_value = {
            "fetched_at": "2025-03-01T00:00:00+00:00",
            "models": [
                {"id": "claude-3-opus", "display_name": "Claude 3 Opus", "created_at": "2024-02-29"},
            ],
        }

        current = [
            {"id": "claude-3-opus", "display_name": "Claude 3 Opus", "created_at": "2024-02-29"},
        ]

        result = diff_models("anthropic_models", current)

        assert result == []
