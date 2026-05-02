import argparse
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
    PODCAST_AUTHOR,
    PODCAST_EMAIL,
    ROOT_DIR,
    SITE_DIR,
    SOURCES,
    SUBSTACK_FEED_DIR,
    SUBSTACK_LOOKBACK_DAYS,
    SUBSTACK_PODCAST_TITLE,
)
from src.ingest import ingest_all
from src.publish import (
    create_episode_item,
    get_episode_metadata,
    update_feed,
)
from src.action_items import generate_action_items, load_memory_slices
from src.email_publish import (
    sections_from_ai_industry_themes,
    sections_from_substack_summaries,
    send_empty_week_email,
    send_episode_email,
    smtp_creds_from_env,
)
from src.scriptgen import generate_script, generate_substack_script
from src.sources.substack_pm import SubstackPMSource
from src.summarize import aggregate_summarize, summarize, summarize_one
from src.tts import synthesize_script

logger = logging.getLogger(__name__)

VALID_SOURCES = ("ai_industry", "substack_pm")


def _try_smtp_creds():
    """Return SmtpCreds dict if env is set, else None (with warning)."""
    try:
        return smtp_creds_from_env()
    except EnvironmentError as e:
        logger.warning("Skipping email send: %s", e)
        return None


def run_pipeline(source: str = "ai_industry", dry_run: bool = False) -> dict:
    """Dispatch by source. ai_industry uses the original pipeline; substack_pm
    routes through the new path (full implementation lands in M3)."""
    if source == "ai_industry":
        return _run_ai_industry(dry_run=dry_run)
    if source == "substack_pm":
        return _run_substack_pm(dry_run=dry_run)
    raise ValueError(f"Unknown source: {source!r} (expected one of {VALID_SOURCES})")


def _run_ai_industry(dry_run: bool = False) -> dict:
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

    # ── Stage 7: Email companion ──────────────────────
    creds = _try_smtp_creds()
    if creds is not None:
        logger.info("Stage 7: Sending AI Industry email digest")
        send_episode_email(
            podcast_name="AI Industry Weekly",
            week_ending=datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            sections=sections_from_ai_industry_themes(themes),
            aggregate=None,
            action_items=None,
            episode_url=metadata["url"],
            creds=creds,
        )

    result["status"] = "published"
    result["episode_title"] = metadata["title"]
    result["mp3_path"] = str(episode_path)
    result["duration"] = metadata["duration"]
    logger.info("Published: %s (%s)", metadata["title"], metadata["duration"])

    return result


def _run_substack_pm(dry_run: bool = False) -> dict:
    """Substack PM pipeline:

    1. Fetch newsletters from Gmail (label:Substack/PM newer_than:7d, dedup against state).
    2. Per-newsletter summary (Claude).
    3. Aggregate summary (Claude).
    4. Action items grounded in role.md/projects.md (Claude).
    5. Two-speaker dialogue (Claude).
    6. TTS + audio stitching.
    7. Publish to site/substack/feed.xml + site/substack/episodes/.
    8. Persist seen message IDs.
    9. Email companion: M4 work — currently a TODO log line.
    """
    result = {
        "status": "skipped",
        "source": "substack_pm",
        "items_count": 0,
        "episode_title": None,
        "mp3_path": None,
        "segments_count": 0,
        "duration": None,
        "errors": [],
    }

    now = datetime.now(timezone.utc)
    week_ending = now.strftime("%Y-%m-%d")

    # ── Stage 1: Ingest ───────────────────────────────
    logger.info("Stage 1: Ingesting Substack newsletters via Gmail")
    src = SubstackPMSource()
    items = src.fetch(since_days=SUBSTACK_LOOKBACK_DAYS)
    result["items_count"] = len(items)
    logger.info("Ingested %d newsletters", len(items))

    if len(items) == 0:
        logger.warning("No newsletters this week")
        creds = _try_smtp_creds()
        if creds is not None:
            send_empty_week_email(
                podcast_name=SUBSTACK_PODCAST_TITLE,
                week_ending=week_ending,
                creds=creds,
            )
        result["status"] = "no_content"
        return result

    # ── Stage 2: Per-newsletter summaries ─────────────
    logger.info("Stage 2: Per-newsletter summaries")
    per_item = [summarize_one(item) for item in items]

    # ── Stage 3: Aggregate ────────────────────────────
    logger.info("Stage 3: Aggregate summary")
    aggregate = aggregate_summarize(per_item, week_ending=week_ending)

    # ── Stage 4: Action items ─────────────────────────
    logger.info("Stage 4: Action items (memory-injected)")
    memory_slices = load_memory_slices()
    action_items = generate_action_items(per_item, aggregate, memory_slices, week_ending=week_ending)

    # ── Stage 5: Script ───────────────────────────────
    logger.info("Stage 5: Generating substack dialogue")
    segments = generate_substack_script(per_item, aggregate, action_items, week_ending=week_ending)
    result["segments_count"] = len(segments)

    if dry_run:
        result["status"] = "dry_run"
        for seg in segments:
            print(f"[{seg['speaker'].upper()}]: {seg['text']}")
        return result

    # ── Stage 6: TTS ──────────────────────────────────
    logger.info("Stage 6: Synthesizing audio via Google TTS")
    segment_paths = synthesize_script(segments)

    # ── Stage 7: Stitch ───────────────────────────────
    logger.info("Stage 7: Stitching audio")
    date_str = now.strftime("%Y-%m-%d")
    episode_filename = f"episode_{date_str}.mp3"
    substack_episodes_dir = ROOT_DIR / SUBSTACK_FEED_DIR / "episodes"
    substack_episodes_dir.mkdir(parents=True, exist_ok=True)
    episode_path = substack_episodes_dir / episode_filename
    stitch_audio(segment_paths, episode_path)

    # ── Stage 8: Publish ──────────────────────────────
    logger.info("Stage 8: Updating Substack RSS feed")
    metadata = get_episode_metadata(
        episode_path,
        PAGES_BASE_URL,
        podcast_title=SUBSTACK_PODCAST_TITLE,
        episode_url_subpath=f"{SUBSTACK_FEED_DIR.removeprefix('site/')}/episodes",
        guid_prefix="substack",
    )
    rss_item = create_episode_item(metadata)
    feed_path = ROOT_DIR / SUBSTACK_FEED_DIR / "feed.xml"
    feed_self_url = (
        f"{PAGES_BASE_URL}/{SUBSTACK_FEED_DIR.removeprefix('site/')}/feed.xml"
        if PAGES_BASE_URL else ""
    )
    channel_config = {
        "PAGES_BASE_URL": PAGES_BASE_URL,
        "PODCAST_TITLE": SUBSTACK_PODCAST_TITLE,
        "PODCAST_DESCRIPTION": "Weekly digest of Fayad's paid Substack PM newsletters — auto-generated.",
        "PODCAST_AUTHOR": PODCAST_AUTHOR,
        "PODCAST_EMAIL": PODCAST_EMAIL,
        "FEED_SELF_URL": feed_self_url,
    }
    update_feed(feed_path, rss_item, channel_config=channel_config)

    # ── Stage 9: Email companion ──────────────────────
    creds = _try_smtp_creds()
    if creds is not None:
        logger.info("Stage 9: Sending Substack email digest")
        send_episode_email(
            podcast_name=SUBSTACK_PODCAST_TITLE,
            week_ending=week_ending,
            sections=sections_from_substack_summaries(per_item),
            aggregate=aggregate,
            action_items=action_items,
            episode_url=metadata["url"],
            creds=creds,
        )

    # ── Stage 10: Persist seen IDs ────────────────────
    src.mark_processed()

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

    parser = argparse.ArgumentParser()
    parser.add_argument("--source", choices=VALID_SOURCES, default="ai_industry")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    result = run_pipeline(source=args.source, dry_run=args.dry_run)
    print(json.dumps(result, indent=2, default=str))
