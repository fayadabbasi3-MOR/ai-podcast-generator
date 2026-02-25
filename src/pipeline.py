import json
import logging
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

from src.audio import stitch_audio
from src.config import (
    EPISODES_DIR,
    LOOKBACK_DAYS,
    PAGES_BASE_URL,
    SITE_DIR,
    SOURCES,
)
from src.ingest import ingest_all
from src.publish import (
    create_episode_item,
    get_episode_metadata,
    update_feed,
)
from src.scriptgen import generate_script
from src.summarize import summarize
from src.tts import synthesize_script

logger = logging.getLogger(__name__)


def run_pipeline(dry_run: bool = False) -> dict:
    """Execute the full pipeline.

    1. ingest_all() — fetch content from all sources
    2. summarize() — Claude API: deduplicate + cluster
    3. generate_script() — Claude API: two-speaker script
    4. synthesize_script() — Google TTS: generate audio segments
    5. stitch_audio() — ffmpeg: combine into single MP3
    6. update_feed() — insert new episode into RSS XML

    Guards:
    - Zero items across all providers → status "skipped"
    - Zero themes from summarize → status "skipped"
    - dry_run=True → stop after script generation
    """
    result = {
        "status": "skipped",
        "episode_title": None,
        "mp3_path": None,
        "themes_count": 0,
        "segments_count": 0,
        "duration": None,
        "errors": [],
    }

    # ── Stage 1: Ingest ───────────────────────────────
    logger.info("Stage 1: Ingesting from %d sources", len(SOURCES))
    content = ingest_all(SOURCES, since_days=LOOKBACK_DAYS)
    result["errors"] = content.get("errors", [])

    total_items = sum(
        len(content.get(p, []))
        for p in ("anthropic", "openai", "gemini")
    )
    logger.info("Ingested %d items (%d errors)", total_items, len(result["errors"]))

    if total_items == 0:
        logger.warning("No content ingested — skipping episode")
        return result

    # ── Stage 2: Summarize ────────────────────────────
    logger.info("Stage 2: Summarizing with Claude API")
    summary = summarize(content)

    themes = summary.get("themes", [])
    result["themes_count"] = len(themes)
    logger.info("Summarized into %d themes", len(themes))

    if len(themes) == 0:
        logger.warning("No themes produced — skipping episode")
        return result

    # ── Stage 3: Script Generation ────────────────────
    logger.info("Stage 3: Generating podcast script")
    segments = generate_script(summary)
    result["segments_count"] = len(segments)
    logger.info("Generated script with %d segments", len(segments))

    if dry_run:
        result["status"] = "dry_run"
        # Print script to stdout
        for seg in segments:
            print(f"[{seg['speaker'].upper()}]: {seg['text']}")
        return result

    # ── Stage 4: TTS ──────────────────────────────────
    logger.info("Stage 4: Synthesizing audio via Google TTS")
    segment_paths = synthesize_script(segments)
    logger.info("Synthesized %d audio segments", len(segment_paths))

    # ── Stage 5: Audio Stitching ──────────────────────
    logger.info("Stage 5: Stitching audio segments")
    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    episode_filename = f"episode_{date_str}.mp3"
    EPISODES_DIR.mkdir(parents=True, exist_ok=True)
    episode_path = EPISODES_DIR / episode_filename
    stitch_audio(segment_paths, episode_path)
    logger.info("Stitched episode: %s", episode_path)

    # ── Stage 6: Publish ──────────────────────────────
    logger.info("Stage 6: Updating RSS feed")
    metadata = get_episode_metadata(episode_path, PAGES_BASE_URL)
    item = create_episode_item(metadata)
    feed_path = SITE_DIR / "feed.xml"
    update_feed(feed_path, item)

    result["status"] = "published"
    result["episode_title"] = metadata["title"]
    result["mp3_path"] = str(episode_path)
    result["duration"] = metadata["duration"]
    logger.info("Published: %s (%s)", metadata["title"], metadata["duration"])

    return result


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    dry_run = "--dry-run" in sys.argv
    result = run_pipeline(dry_run=dry_run)
    print(json.dumps(result, indent=2))
