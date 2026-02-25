"""
Local CLI for running individual pipeline stages or the full pipeline.

Usage:
    python scripts/run_local.py --stage ingest
    python scripts/run_local.py --stage ingest --source anthropic_blog
    python scripts/run_local.py --stage summarize --input ingest_output.json
    python scripts/run_local.py --stage script --input summarize_output.json
    python scripts/run_local.py --stage tts --input script_output.json
    python scripts/run_local.py --stage all
    python scripts/run_local.py --stage all --dry-run

Arguments:
    --stage     Required. One of: ingest, summarize, script, tts, audio, publish, all
    --source    Optional. Run ingest for a single source by name.
    --input     Optional. Path to JSON file to use as input (skip prior stages).
    --dry-run   Optional. Stop after script generation (no TTS/audio/publish).
    --output    Optional. Write stage output to a JSON file (default: stdout).
"""

import argparse
import json
import logging
import sys
from pathlib import Path

# Ensure project root is on sys.path so `from src.…` works
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config import LOOKBACK_DAYS, SOURCES
from src.ingest import ingest_all
from src.summarize import summarize
from src.scriptgen import generate_script
from src.tts import synthesize_script
from src.audio import stitch_audio
from src.publish import create_episode_item, get_episode_metadata, update_feed
from src.pipeline import run_pipeline
from src.config import EPISODES_DIR, PAGES_BASE_URL, SITE_DIR

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


def _load_input(path: str) -> dict | list:
    with open(path) as f:
        return json.load(f)


def _write_output(data, output_path: str | None) -> None:
    text = json.dumps(data, indent=2, ensure_ascii=False, default=str)
    if output_path:
        Path(output_path).write_text(text)
        logger.info("Output written to %s", output_path)
    else:
        print(text)


def run_ingest(args):
    sources = SOURCES
    if args.source:
        sources = [s for s in SOURCES if s["name"] == args.source]
        if not sources:
            logger.error("Source '%s' not found in config.SOURCES", args.source)
            sys.exit(1)

    result = ingest_all(sources, since_days=LOOKBACK_DAYS)
    _write_output(result, args.output)


def run_summarize(args):
    if not args.input:
        logger.error("--input required for summarize stage")
        sys.exit(1)
    content = _load_input(args.input)
    result = summarize(content)
    _write_output(result, args.output)


def run_script(args):
    if not args.input:
        logger.error("--input required for script stage")
        sys.exit(1)
    themes = _load_input(args.input)
    segments = generate_script(themes)
    _write_output(segments, args.output)


def run_tts(args):
    if not args.input:
        logger.error("--input required for tts stage")
        sys.exit(1)
    segments = _load_input(args.input)
    paths = synthesize_script(segments)
    _write_output([str(p) for p in paths], args.output)


def run_audio(args):
    if not args.input:
        logger.error("--input required for audio stage")
        sys.exit(1)
    segment_paths = [Path(p) for p in _load_input(args.input)]
    from datetime import datetime, timezone
    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    EPISODES_DIR.mkdir(parents=True, exist_ok=True)
    output_path = EPISODES_DIR / f"episode_{date_str}.mp3"
    stitch_audio(segment_paths, output_path)
    _write_output({"mp3_path": str(output_path)}, args.output)


def run_publish(args):
    if not args.input:
        logger.error("--input required for publish stage (path to mp3)")
        sys.exit(1)
    data = _load_input(args.input)
    mp3_path = Path(data["mp3_path"])
    metadata = get_episode_metadata(mp3_path, PAGES_BASE_URL)
    item = create_episode_item(metadata)
    feed_path = SITE_DIR / "feed.xml"
    update_feed(feed_path, item)
    _write_output(metadata, args.output)


def run_all(args):
    result = run_pipeline(dry_run=args.dry_run)
    _write_output(result, args.output)


STAGE_HANDLERS = {
    "ingest": run_ingest,
    "summarize": run_summarize,
    "script": run_script,
    "tts": run_tts,
    "audio": run_audio,
    "publish": run_publish,
    "all": run_all,
}


def main():
    parser = argparse.ArgumentParser(
        description="Run AI Podcast Generator pipeline stages locally.",
    )
    parser.add_argument(
        "--stage",
        required=True,
        choices=STAGE_HANDLERS.keys(),
        help="Pipeline stage to run.",
    )
    parser.add_argument(
        "--source",
        help="Run ingest for a single source by name.",
    )
    parser.add_argument(
        "--input",
        help="Path to JSON file to use as input (skip prior stages).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Stop after script generation (no TTS/audio/publish).",
    )
    parser.add_argument(
        "--output",
        help="Write stage output to a JSON file (default: stdout).",
    )

    args = parser.parse_args()
    handler = STAGE_HANDLERS[args.stage]
    handler(args)


if __name__ == "__main__":
    main()
