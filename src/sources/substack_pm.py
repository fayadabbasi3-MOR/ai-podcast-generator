import json
import logging
import re
from datetime import datetime, timezone
from email.utils import parseaddr
from pathlib import Path

from src.config import ROOT_DIR, SUBSTACK_GMAIL_LABEL, SUBSTACK_SEEN_FILE
from src.sources import ContentItem
from src.sources._gmail_client import fetch_messages
from src.sources._substack_body import BodyTooShort, extract_post

logger = logging.getLogger(__name__)


class SubstackPMSource:
    name = "substack_pm"

    def __init__(self, seen_file_path: Path | None = None):
        self._seen_path = Path(seen_file_path) if seen_file_path else (ROOT_DIR / SUBSTACK_SEEN_FILE)
        self._pending_seen_ids: list[str] = []

    def fetch(self, since_days: int = 7, gmail_service=None) -> list[ContentItem]:
        seen_ids = _load_seen_ids(self._seen_path)
        query = f"label:{SUBSTACK_GMAIL_LABEL} newer_than:{since_days}d"

        messages = fetch_messages(query, service=gmail_service)
        logger.info("substack_pm: %d messages from gmail", len(messages))

        items: list[ContentItem] = []
        skipped_short = 0
        skipped_dup = 0

        for msg in messages:
            msg_id = msg["id"]
            if msg_id in seen_ids:
                skipped_dup += 1
                continue
            try:
                url, body = extract_post(msg.get("html_body") or "")
            except BodyTooShort as e:
                logger.info("substack_pm: skipping %s (%s)", msg_id, e)
                skipped_short += 1
                continue

            headers = msg.get("headers", {}) or {}
            subject = headers.get("subject", "")
            from_header = headers.get("from", "")
            author_name, author_email = parseaddr(from_header)

            items.append(ContentItem(
                id=msg_id,
                title=_clean_subject(subject),
                url=url,
                author=author_name or None,
                published=_parse_internal_date(msg.get("internal_date")),
                body_text=body,
                source_meta={
                    "publication": author_name or _publication_from_email(author_email),
                    "from_email": author_email,
                    "gmail_message_id": msg_id,
                },
            ))
            self._pending_seen_ids.append(msg_id)

        logger.info(
            "substack_pm: %d items extracted, %d duplicates, %d short/parse-skipped",
            len(items), skipped_dup, skipped_short,
        )
        return items

    def mark_processed(self, item_ids: list[str] | None = None) -> None:
        ids_to_persist = item_ids if item_ids is not None else self._pending_seen_ids
        if not ids_to_persist:
            return
        state = _load_state(self._seen_path)
        existing = set(state.get("seen_message_ids", []))
        existing.update(ids_to_persist)
        state["seen_message_ids"] = sorted(existing)
        state["last_run_utc"] = datetime.now(timezone.utc).isoformat()
        self._seen_path.parent.mkdir(parents=True, exist_ok=True)
        self._seen_path.write_text(json.dumps(state, indent=2) + "\n")
        logger.info("substack_pm: persisted %d ids to %s", len(ids_to_persist), self._seen_path)


def _load_state(path: Path) -> dict:
    if not path.exists():
        return {"last_run_utc": None, "seen_message_ids": [], "retention_days": 30}
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("substack_pm: state file corrupt (%s), resetting", e)
        return {"last_run_utc": None, "seen_message_ids": [], "retention_days": 30}


def _load_seen_ids(path: Path) -> set[str]:
    return set(_load_state(path).get("seen_message_ids", []))


_FORWARD_PREFIX_RE = re.compile(r"^(?:re|fwd?|fw)\s*:\s*", re.IGNORECASE)


def _clean_subject(subject: str) -> str:
    s = subject.strip()
    while True:
        new = _FORWARD_PREFIX_RE.sub("", s)
        if new == s:
            return s
        s = new


def _parse_internal_date(internal_date: str | None) -> datetime:
    if not internal_date:
        return datetime.now(timezone.utc)
    try:
        ms = int(internal_date)
        return datetime.fromtimestamp(ms / 1000.0, tz=timezone.utc)
    except (ValueError, TypeError):
        return datetime.now(timezone.utc)


def _publication_from_email(email: str) -> str:
    if "@" not in email:
        return ""
    local = email.split("@", 1)[0]
    return local.replace(".", " ").replace("-", " ").title()
