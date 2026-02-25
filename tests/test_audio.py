from pathlib import Path
from unittest.mock import patch, MagicMock, call

import pytest

from src.audio import (
    generate_silence,
    stitch_audio,
    get_mp3_duration_seconds,
    format_duration_itunes,
)


# ── generate_silence ──────────────────────────────────


class TestGenerateSilence:
    @patch("src.audio.subprocess.run")
    def test_calls_ffmpeg(self, mock_run):
        """Verify ffmpeg command for silence generation."""
        mock_run.return_value = MagicMock(returncode=0)
        output = Path("/tmp/silence.mp3")

        result = generate_silence(400, output)

        assert result == output
        mock_run.assert_called_once()
        cmd = mock_run.call_args[0][0]
        assert "ffmpeg" in cmd
        assert "anullsrc=r=24000:cl=mono" in cmd
        assert "0.4" in cmd  # 400ms = 0.4s
        assert "libmp3lame" in cmd

    @patch("src.audio.subprocess.run")
    def test_duration_conversion(self, mock_run):
        """Duration in ms is correctly converted to seconds."""
        mock_run.return_value = MagicMock(returncode=0)

        generate_silence(1500, Path("/tmp/silence.mp3"))

        cmd = mock_run.call_args[0][0]
        assert "1.5" in cmd


# ── stitch_audio ───────────────────────────────────────


class TestStitchAudio:
    @patch("src.audio.subprocess.run")
    def test_creates_concat_list(self, mock_run):
        """Verify the concat list file has correct format."""
        mock_run.return_value = MagicMock(returncode=0)

        seg_paths = [
            Path("/tmp/segment_000.mp3"),
            Path("/tmp/segment_001.mp3"),
            Path("/tmp/segment_002.mp3"),
        ]
        output = Path("/tmp/episode.mp3")

        stitch_audio(seg_paths, output)

        # Two subprocess calls: generate_silence + concat
        assert mock_run.call_count == 2

        # The concat call is the second one
        concat_cmd = mock_run.call_args_list[1][0][0]
        assert "concat" in concat_cmd
        assert "-safe" in concat_cmd

    @patch("src.audio.subprocess.run")
    def test_concat_list_format(self, mock_run):
        """Concat list alternates segments and silence, no trailing silence."""
        mock_run.return_value = MagicMock(returncode=0)

        seg_paths = [
            Path("/tmp/seg_000.mp3"),
            Path("/tmp/seg_001.mp3"),
        ]

        stitch_audio(seg_paths, Path("/tmp/out.mp3"))

        # Find the concat list path from the second ffmpeg call
        concat_cmd = mock_run.call_args_list[1][0][0]
        # The -i argument is the concat list path
        i_idx = concat_cmd.index("-i")
        concat_list_path = Path(concat_cmd[i_idx + 1])
        content = concat_list_path.read_text()

        lines = [l for l in content.strip().split("\n") if l]
        # 2 segments + 1 silence between them = 3 lines
        assert len(lines) == 3
        assert "seg_000.mp3" in lines[0]
        assert "silence.mp3" in lines[1]
        assert "seg_001.mp3" in lines[2]

    @patch("src.audio.subprocess.run")
    def test_single_segment_no_silence(self, mock_run):
        """Single segment produces no silence entries in concat list."""
        mock_run.return_value = MagicMock(returncode=0)

        seg_paths = [Path("/tmp/seg_000.mp3")]

        stitch_audio(seg_paths, Path("/tmp/out.mp3"))

        concat_cmd = mock_run.call_args_list[1][0][0]
        i_idx = concat_cmd.index("-i")
        concat_list_path = Path(concat_cmd[i_idx + 1])
        content = concat_list_path.read_text()

        lines = [l for l in content.strip().split("\n") if l]
        assert len(lines) == 1
        assert "silence" not in lines[0]


# ── get_mp3_duration_seconds ───────────────────────────


class TestGetMp3DurationSeconds:
    def test_calculation(self, tmp_path):
        """(1_000_000 * 8) / 128_000 == 62.5 seconds."""
        mp3 = tmp_path / "test.mp3"
        mp3.write_bytes(b"\x00" * 1_000_000)

        result = get_mp3_duration_seconds(mp3)

        assert result == 62.5

    def test_small_file(self, tmp_path):
        """Small file gives proportionally small duration."""
        mp3 = tmp_path / "small.mp3"
        mp3.write_bytes(b"\x00" * 16_000)  # 16KB

        result = get_mp3_duration_seconds(mp3)

        assert result == 1.0  # (16000 * 8) / 128000 = 1.0


# ── format_duration_itunes ─────────────────────────────


class TestFormatDurationItunes:
    def test_standard_duration(self):
        """485.7 seconds -> '00:08:05'"""
        assert format_duration_itunes(485.7) == "00:08:05"

    def test_exact_hour(self):
        """3600 seconds -> '01:00:00'"""
        assert format_duration_itunes(3600) == "01:00:00"

    def test_zero(self):
        """0 seconds -> '00:00:00'"""
        assert format_duration_itunes(0) == "00:00:00"

    def test_long_episode(self):
        """3725.3 seconds -> '01:02:05'"""
        assert format_duration_itunes(3725.3) == "01:02:05"
