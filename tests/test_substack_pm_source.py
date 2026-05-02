import json
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import pytest

from src.sources.substack_pm import SubstackPMSource


SAMPLE_HTML = (Path(__file__).parent / "fixtures" / "substack_sample.html").read_text()


def _gmail_message(msg_id: str, subject: str, from_addr: str, html: str = SAMPLE_HTML, internal_date: str = "1700000000000") -> dict:
    return {
        "id": msg_id,
        "internal_date": internal_date,
        "headers": {"subject": subject, "from": from_addr},
        "html_body": html,
        "plain_body": "",
    }


@pytest.fixture
def state_path(tmp_path):
    p = tmp_path / "state" / "substack_seen.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"last_run_utc": None, "seen_message_ids": [], "retention_days": 30}))
    return p


class TestFetch:
    @patch("src.sources.substack_pm.fetch_messages")
    def test_returns_content_items(self, mock_fetch, state_path):
        mock_fetch.return_value = [
            _gmail_message("m1", "Build vs Buy Trap", "Lenny <lenny@substack.com>"),
        ]
        items = SubstackPMSource(seen_file_path=state_path).fetch(since_days=7)

        assert len(items) == 1
        item = items[0]
        assert item["id"] == "m1"
        assert item["title"] == "Build vs Buy Trap"
        assert item["url"].startswith("https://")
        assert item["author"] == "Lenny"
        assert isinstance(item["published"], datetime)
        assert len(item["body_text"]) > 500
        assert item["source_meta"]["publication"] == "Lenny"

    @patch("src.sources.substack_pm.fetch_messages")
    def test_dedup_filters_known_ids(self, mock_fetch, state_path):
        state_path.write_text(json.dumps({
            "last_run_utc": None,
            "seen_message_ids": ["already_seen"],
            "retention_days": 30,
        }))
        mock_fetch.return_value = [
            _gmail_message("already_seen", "Old", "x@substack.com"),
            _gmail_message("new_id", "New", "x@substack.com"),
        ]
        items = SubstackPMSource(seen_file_path=state_path).fetch()
        assert [i["id"] for i in items] == ["new_id"]

    @patch("src.sources.substack_pm.fetch_messages")
    def test_skips_short_bodies(self, mock_fetch, state_path):
        mock_fetch.return_value = [
            _gmail_message("short", "Tiny", "x@substack.com", html="<html><body><p>too short</p></body></html>"),
            _gmail_message("ok", "Real", "x@substack.com"),
        ]
        items = SubstackPMSource(seen_file_path=state_path).fetch()
        assert [i["id"] for i in items] == ["ok"]

    @patch("src.sources.substack_pm.fetch_messages")
    def test_strips_re_fwd_subject_prefixes(self, mock_fetch, state_path):
        mock_fetch.return_value = [
            _gmail_message("m1", "Re: Fwd: Build vs Buy Trap", "x@substack.com"),
        ]
        items = SubstackPMSource(seen_file_path=state_path).fetch()
        assert items[0]["title"] == "Build vs Buy Trap"

    @patch("src.sources.substack_pm.fetch_messages")
    def test_uses_substack_gmail_query(self, mock_fetch, state_path):
        mock_fetch.return_value = []
        SubstackPMSource(seen_file_path=state_path).fetch(since_days=14)
        query = mock_fetch.call_args.args[0]
        assert "label:Substack/PM" in query
        assert "newer_than:14d" in query


class TestMarkProcessed:
    @patch("src.sources.substack_pm.fetch_messages")
    def test_persists_pending_ids(self, mock_fetch, state_path):
        mock_fetch.return_value = [
            _gmail_message("a", "A", "x@substack.com"),
            _gmail_message("b", "B", "x@substack.com"),
        ]
        src = SubstackPMSource(seen_file_path=state_path)
        src.fetch()
        src.mark_processed()

        state = json.loads(state_path.read_text())
        assert set(state["seen_message_ids"]) == {"a", "b"}
        assert state["last_run_utc"] is not None

    @patch("src.sources.substack_pm.fetch_messages")
    def test_explicit_ids_override_pending(self, mock_fetch, state_path):
        mock_fetch.return_value = [_gmail_message("a", "A", "x@substack.com")]
        src = SubstackPMSource(seen_file_path=state_path)
        src.fetch()
        src.mark_processed(["custom_id"])
        state = json.loads(state_path.read_text())
        assert state["seen_message_ids"] == ["custom_id"]

    def test_noop_when_no_pending(self, state_path):
        before = state_path.read_text()
        SubstackPMSource(seen_file_path=state_path).mark_processed()
        assert state_path.read_text() == before

    @patch("src.sources.substack_pm.fetch_messages")
    def test_appends_to_existing_seen(self, mock_fetch, state_path):
        state_path.write_text(json.dumps({
            "last_run_utc": "2026-04-01T00:00:00+00:00",
            "seen_message_ids": ["old1", "old2"],
            "retention_days": 30,
        }))
        mock_fetch.return_value = [_gmail_message("new1", "X", "x@substack.com")]
        src = SubstackPMSource(seen_file_path=state_path)
        src.fetch()
        src.mark_processed()
        state = json.loads(state_path.read_text())
        assert set(state["seen_message_ids"]) == {"old1", "old2", "new1"}
