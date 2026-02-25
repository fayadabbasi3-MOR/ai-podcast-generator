from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from src.tts import text_to_chunks, synthesize_segment, synthesize_script
from src.config import TTS_CHUNK_BYTE_LIMIT, INTERVIEWER_VOICE, EXPERT_VOICE


# ── text_to_chunks ─────────────────────────────────────


class TestTextToChunks:
    def test_respects_byte_limit(self):
        """No chunk exceeds TTS_CHUNK_BYTE_LIMIT bytes (UTF-8)."""
        # Create text that's well over the limit
        text = "This is a sentence. " * 500  # ~10,000 chars

        chunks = text_to_chunks(text)

        for chunk in chunks:
            assert len(chunk.encode("utf-8")) <= TTS_CHUNK_BYTE_LIMIT, (
                f"Chunk exceeds byte limit: {len(chunk.encode('utf-8'))} bytes"
            )

    def test_splits_on_sentences(self):
        """Prefers sentence boundaries over mid-word splits."""
        text = "First sentence. Second sentence. Third sentence."

        # Use a byte limit that fits ~2 sentences but not all 3
        chunks = text_to_chunks(text, byte_limit=35)

        # Should not split mid-sentence
        for chunk in chunks:
            assert not chunk.startswith("entence"), f"Chunk split mid-word: {chunk}"

    def test_short_text_returns_single_chunk(self):
        """Text under the limit comes back as one chunk."""
        text = "Short text."

        chunks = text_to_chunks(text)

        assert len(chunks) == 1
        assert chunks[0] == text

    def test_handles_utf8_multibyte(self):
        """Byte limit accounts for multi-byte UTF-8 characters."""
        # Each emoji is 4 bytes in UTF-8
        text = "\U0001f600 " * 1500  # ~6000 bytes of emojis

        chunks = text_to_chunks(text)

        for chunk in chunks:
            assert len(chunk.encode("utf-8")) <= TTS_CHUNK_BYTE_LIMIT

    def test_splits_long_sentence_on_clauses(self):
        """A single sentence exceeding the limit splits on clause boundaries."""
        clauses = ["clause number " + str(i) for i in range(100)]
        text = ", ".join(clauses) + "."

        chunks = text_to_chunks(text, byte_limit=200)

        for chunk in chunks:
            assert len(chunk.encode("utf-8")) <= 200

    def test_splits_on_words_as_last_resort(self):
        """If clauses are still too long, falls back to word splitting."""
        # One giant 'sentence' with no clause delimiters
        text = "word " * 1500

        chunks = text_to_chunks(text, byte_limit=100)

        for chunk in chunks:
            assert len(chunk.encode("utf-8")) <= 100


# ── synthesize_segment ─────────────────────────────────


class TestSynthesizeSegment:
    @patch("src.tts.texttospeech.TextToSpeechClient")
    def test_returns_bytes(self, mock_client_cls):
        """Mock client returns audio content bytes."""
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client
        mock_response = MagicMock()
        mock_response.audio_content = b"\xff\xfb\x90\x00" * 100  # fake MP3 bytes
        mock_client.synthesize_speech.return_value = mock_response

        result = synthesize_segment("Hello world", INTERVIEWER_VOICE)

        assert isinstance(result, bytes)
        assert len(result) > 0
        mock_client.synthesize_speech.assert_called_once()

    @patch("src.tts.time.sleep")
    @patch("src.tts.texttospeech.TextToSpeechClient")
    def test_retries_on_failure(self, mock_client_cls, mock_sleep):
        """Retries on API errors with backoff."""
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client

        mock_response = MagicMock()
        mock_response.audio_content = b"\xff\xfb\x90\x00"

        mock_client.synthesize_speech.side_effect = [
            Exception("API error"),
            mock_response,
        ]

        result = synthesize_segment("Hello", EXPERT_VOICE)

        assert result == b"\xff\xfb\x90\x00"
        assert mock_sleep.call_count == 1


# ── synthesize_script ──────────────────────────────────


class TestSynthesizeScript:
    @patch("src.tts.synthesize_segment")
    def test_produces_mp3_files(self, mock_synth):
        """Each segment produces a .mp3 file in order."""
        mock_synth.return_value = b"\xff\xfb\x90\x00" * 10

        segments = [
            {"speaker": "interviewer", "text": "Hello."},
            {"speaker": "expert", "text": "Hi there."},
            {"speaker": "interviewer", "text": "Let us begin."},
            {"speaker": "expert", "text": "Sure thing."},
        ]

        paths = synthesize_script(segments)

        assert len(paths) == 4
        for p in paths:
            assert p.suffix == ".mp3"
            assert p.exists()
            assert p.stat().st_size > 0

    @patch("src.tts.synthesize_segment")
    def test_substitutes_silence_on_failure(self, mock_synth):
        """Single chunk failure produces silence (empty bytes), not crash."""
        call_count = 0

        def side_effect(text, voice):
            nonlocal call_count
            call_count += 1
            if call_count == 2:
                raise Exception("TTS failed")
            return b"\xff\xfb\x90\x00" * 10

        mock_synth.side_effect = side_effect

        segments = [
            {"speaker": "interviewer", "text": "First segment."},
            {"speaker": "expert", "text": "Second segment."},
            {"speaker": "interviewer", "text": "Third segment."},
            {"speaker": "expert", "text": "Fourth segment."},
            {"speaker": "interviewer", "text": "Fifth segment."},
        ]

        # Should not raise — 1/5 chunks is 20%, under the 30% threshold
        paths = synthesize_script(segments)

        assert len(paths) == 5

    @patch("src.tts.synthesize_segment")
    def test_aborts_on_mass_failure(self, mock_synth):
        """>30% chunk failure raises RuntimeError."""
        call_count = 0

        def side_effect(text, voice):
            nonlocal call_count
            call_count += 1
            if call_count <= 2:
                return b"\xff\xfb\x90\x00"
            raise Exception("TTS failed")

        mock_synth.side_effect = side_effect

        # 10 segments: first 2 succeed, next 8 fail -> 80% failure
        segments = [
            {"speaker": "interviewer" if i % 2 == 0 else "expert", "text": f"Segment {i}."}
            for i in range(10)
        ]

        with pytest.raises(RuntimeError, match="TTS abort"):
            synthesize_script(segments)

    @patch("src.tts.synthesize_segment")
    def test_selects_correct_voice(self, mock_synth):
        """Interviewer uses INTERVIEWER_VOICE, expert uses EXPERT_VOICE."""
        mock_synth.return_value = b"\xff\xfb\x90\x00"

        segments = [
            {"speaker": "interviewer", "text": "Hello."},
            {"speaker": "expert", "text": "Hi."},
            {"speaker": "interviewer", "text": "Topic one."},
            {"speaker": "expert", "text": "Good point."},
        ]

        synthesize_script(segments)

        calls = mock_synth.call_args_list
        assert calls[0][0][1] == INTERVIEWER_VOICE
        assert calls[1][0][1] == EXPERT_VOICE
        assert calls[2][0][1] == INTERVIEWER_VOICE
        assert calls[3][0][1] == EXPERT_VOICE
