import hashlib
import json
import logging
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from src.config import ROOT_DIR

logger = logging.getLogger(__name__)

SNAPSHOTS_DIR = ROOT_DIR / "snapshots"


def load_previous_snapshot(source_name: str) -> dict | None:
    """Read the previous snapshot from the snapshots branch via:
      git show origin/snapshots:snapshots/{source_name}.json

    Returns parsed JSON dict, or None if branch/file doesn't exist.
    No branch checkout — reads the blob directly.
    """
    blob_path = f"snapshots/{source_name}.json"
    try:
        result = subprocess.run(
            ["git", "show", f"origin/snapshots:{blob_path}"],
            capture_output=True,
            text=True,
            cwd=ROOT_DIR,
        )
        if result.returncode != 0:
            logger.info("No previous snapshot for %s (branch or file missing)", source_name)
            return None
        return json.loads(result.stdout)
    except (json.JSONDecodeError, Exception) as e:
        logger.warning("Failed to load snapshot for %s: %s", source_name, e)
        return None


def save_snapshot(source_name: str, data: dict) -> None:
    """Write data as JSON to snapshots/{source_name}.json in the working directory.

    The GitHub Actions workflow handles committing this to the snapshots branch.
    """
    SNAPSHOTS_DIR.mkdir(parents=True, exist_ok=True)
    path = SNAPSHOTS_DIR / f"{source_name}.json"
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False))
    logger.info("Saved snapshot for %s to %s", source_name, path)


def diff_scrape(source_name: str, current_text: str) -> str | None:
    """Compare current scraped text against previous snapshot.

    Returns the new/changed text if different, None if unchanged.
    Uses content_hash (SHA-256 of text) for quick equality check.
    """
    current_hash = hashlib.sha256(current_text.encode()).hexdigest()
    now = datetime.now(timezone.utc).isoformat()

    previous = load_previous_snapshot(source_name)

    # Save current snapshot regardless
    save_snapshot(source_name, {
        "fetched_at": now,
        "content_hash": current_hash,
        "raw_text": current_text,
    })

    if previous is None:
        # First run — treat everything as new
        return current_text

    if previous.get("content_hash") == current_hash:
        return None

    return current_text


def diff_sitemap(source_name: str, current_urls: dict[str, str | None]) -> list[str]:
    """Compare current sitemap URLs against previous snapshot.

    Returns list of new URLs (present in current but not in previous).
    For sitemaps with lastmod: also returns URLs whose lastmod changed.
    """
    now = datetime.now(timezone.utc).isoformat()

    previous = load_previous_snapshot(source_name)

    # Save current snapshot regardless
    save_snapshot(source_name, {
        "fetched_at": now,
        "urls": current_urls,
    })

    if previous is None:
        # First run — all URLs are new
        return list(current_urls.keys())

    prev_urls = previous.get("urls", {})
    new_urls = []

    for url, lastmod in current_urls.items():
        if url not in prev_urls:
            new_urls.append(url)
        elif lastmod and lastmod != prev_urls.get(url):
            # lastmod changed — content was updated
            new_urls.append(url)

    return new_urls


def diff_models(source_name: str, current_models: list[dict]) -> list[dict]:
    """Compare current model list against previous snapshot.

    Returns list of new models (model IDs present now but not before).
    """
    now = datetime.now(timezone.utc).isoformat()

    previous = load_previous_snapshot(source_name)

    # Save current snapshot regardless
    save_snapshot(source_name, {
        "fetched_at": now,
        "models": current_models,
    })

    if previous is None:
        # First run — all models are new
        return current_models

    prev_ids = {m["id"] for m in previous.get("models", [])}
    return [m for m in current_models if m["id"] not in prev_ids]
