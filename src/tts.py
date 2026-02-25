import logging
import tempfile
import time
from pathlib import Path

from google.cloud import texttospeech

from src.config import (
    EXPERT_VOICE,
    INTERVIEWER_VOICE,
    TTS_CHUNK_BYTE_LIMIT,
)

logger = logging.getLogger(__name__)

TTS_RETRY_DELAYS = [2, 8, 32]


def text_to_chunks(text: str, byte_limit: int = TTS_CHUNK_BYTE_LIMIT) -> list[str]:
    """Split text into chunks that fit within the byte limit.

    Split strategy:
    1. Split on sentence boundaries (". ", "! ", "? ").
    2. If a single sentence exceeds the limit, split on clause boundaries (", ", "; ", " — ").
    3. If a clause still exceeds, split on word boundaries.

    Byte length is checked with len(chunk.encode('utf-8')), NOT len(chunk).
    """
    if len(text.encode("utf-8")) <= byte_limit:
        return [text]

    # Split into sentences
    sentences = _split_keeping_delimiters(text, [". ", "! ", "? "])
    chunks = []
    current = ""

    for sentence in sentences:
        candidate = current + sentence if current else sentence
        if len(candidate.encode("utf-8")) <= byte_limit:
            current = candidate
        else:
            if current:
                chunks.append(current)
            # Check if this single sentence fits
            if len(sentence.encode("utf-8")) <= byte_limit:
                current = sentence
            else:
                # Sentence too long — split on clause boundaries
                clause_chunks = _split_large_text(sentence, byte_limit)
                chunks.extend(clause_chunks[:-1])
                current = clause_chunks[-1]

    if current:
        chunks.append(current)

    return chunks


def synthesize_segment(text: str, voice_config: dict) -> bytes:
    """Call Google Cloud TTS for a single text chunk.

    Returns raw MP3 bytes.
    Retry: 3 attempts with exponential backoff on API errors.
    """
    client = texttospeech.TextToSpeechClient()

    synthesis_input = texttospeech.SynthesisInput(text=text)
    voice = texttospeech.VoiceSelectionParams(
        language_code=voice_config["language_code"],
        name=voice_config["name"],
        ssml_gender=getattr(
            texttospeech.SsmlVoiceGender, voice_config["ssml_gender"]
        ),
    )
    audio_config = texttospeech.AudioConfig(
        audio_encoding=texttospeech.AudioEncoding.MP3
    )

    for attempt, delay in enumerate(TTS_RETRY_DELAYS):
        try:
            response = client.synthesize_speech(
                input=synthesis_input, voice=voice, audio_config=audio_config
            )
            return response.audio_content
        except Exception as e:
            if attempt < len(TTS_RETRY_DELAYS) - 1:
                logger.warning(
                    "TTS error (attempt %d/%d), retrying in %ds: %s",
                    attempt + 1, len(TTS_RETRY_DELAYS), delay, e,
                )
                time.sleep(delay)
            else:
                raise

    raise RuntimeError("All TTS retries exhausted")


def synthesize_script(segments: list[dict]) -> list[Path]:
    """Process all script segments through TTS.

    For each segment:
    1. Select voice config based on segment["speaker"]
    2. Chunk the text with text_to_chunks()
    3. Synthesize each chunk with synthesize_segment()
    4. Concatenate chunk bytes and write to a temp .mp3 file

    If a single chunk fails after retries, substitute silence.
    If >30% of total chunks fail, raise RuntimeError (abort episode).
    """
    tmp_dir = Path(tempfile.mkdtemp(prefix="tts_"))
    segment_paths = []

    total_chunks = 0
    failed_chunks = 0

    for i, segment in enumerate(segments):
        voice_config = (
            INTERVIEWER_VOICE
            if segment["speaker"] == "interviewer"
            else EXPERT_VOICE
        )

        chunks = text_to_chunks(segment["text"])
        total_chunks += len(chunks)
        audio_parts = []

        for chunk in chunks:
            try:
                audio_bytes = synthesize_segment(chunk, voice_config)
                audio_parts.append(audio_bytes)
            except Exception as e:
                logger.warning(
                    "Chunk failed for segment %d, substituting silence: %s", i, e
                )
                failed_chunks += 1
                # Substitute ~1 second of silence (empty bytes — will be
                # handled by audio.generate_silence in the stitching phase)
                audio_parts.append(b"")

        # Write concatenated audio to temp file
        segment_path = tmp_dir / f"segment_{i:03d}.mp3"
        with open(segment_path, "wb") as f:
            for part in audio_parts:
                f.write(part)
        segment_paths.append(segment_path)

    # Check abort threshold after processing all segments
    if total_chunks > 0 and (failed_chunks / total_chunks) > 0.3:
        raise RuntimeError(
            f"TTS abort: {failed_chunks}/{total_chunks} chunks failed (>30%)"
        )

    return segment_paths


# ── Helpers ────────────────────────────────────────────


def _split_keeping_delimiters(text: str, delimiters: list[str]) -> list[str]:
    """Split text on delimiters, keeping the delimiter attached to the preceding part."""
    parts = [text]
    for delim in delimiters:
        new_parts = []
        for part in parts:
            splits = part.split(delim)
            for j, s in enumerate(splits):
                if j < len(splits) - 1:
                    new_parts.append(s + delim)
                else:
                    if s:
                        new_parts.append(s)
        parts = new_parts
    return parts


def _split_large_text(text: str, byte_limit: int) -> list[str]:
    """Split a single too-large text on clause then word boundaries."""
    # Try clause boundaries first
    clause_delimiters = [", ", "; ", " — "]
    clauses = _split_keeping_delimiters(text, clause_delimiters)

    chunks = []
    current = ""

    for clause in clauses:
        candidate = current + clause if current else clause
        if len(candidate.encode("utf-8")) <= byte_limit:
            current = candidate
        else:
            if current:
                chunks.append(current)
            if len(clause.encode("utf-8")) <= byte_limit:
                current = clause
            else:
                # Clause still too long — split on words
                word_chunks = _split_on_words(clause, byte_limit)
                chunks.extend(word_chunks[:-1])
                current = word_chunks[-1]

    if current:
        chunks.append(current)

    return chunks


def _split_on_words(text: str, byte_limit: int) -> list[str]:
    """Last resort: split on word boundaries."""
    words = text.split(" ")
    chunks = []
    current = ""

    for word in words:
        candidate = current + " " + word if current else word
        if len(candidate.encode("utf-8")) <= byte_limit:
            current = candidate
        else:
            if current:
                chunks.append(current)
            current = word

    if current:
        chunks.append(current)

    return chunks
