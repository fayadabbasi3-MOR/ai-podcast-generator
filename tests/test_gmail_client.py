import base64
from unittest.mock import MagicMock, patch

import pytest

from src.sources import _gmail_client


def _b64(s: str) -> str:
    return base64.urlsafe_b64encode(s.encode("utf-8")).decode("ascii")


def _mock_service_with_messages(message_pages, message_payloads):
    """Build a mock Gmail service that returns paginated message lists and per-id payloads."""
    svc = MagicMock()
    list_call = svc.users.return_value.messages.return_value.list
    get_call = svc.users.return_value.messages.return_value.get

    def list_side_effect(**kwargs):
        token = kwargs.get("pageToken")
        page_idx = 0 if token is None else int(token)
        page = message_pages[page_idx]
        next_token = str(page_idx + 1) if page_idx + 1 < len(message_pages) else None
        exec_mock = MagicMock()
        exec_mock.execute.return_value = {
            "messages": [{"id": mid} for mid in page],
            **({"nextPageToken": next_token} if next_token else {}),
        }
        return exec_mock

    list_call.side_effect = list_side_effect

    def get_side_effect(userId, id, format):
        exec_mock = MagicMock()
        exec_mock.execute.return_value = message_payloads[id]
        return exec_mock

    get_call.side_effect = get_side_effect
    return svc


class TestListMessageIds:
    def test_paginates(self):
        svc = _mock_service_with_messages([["a", "b"], ["c"]], {})
        ids = list(_gmail_client.list_message_ids("label:Substack/PM newer_than:7d", service=svc))
        assert ids == ["a", "b", "c"]

    def test_empty(self):
        svc = _mock_service_with_messages([[]], {})
        assert list(_gmail_client.list_message_ids("q", service=svc)) == []


class TestGetMessage:
    def test_extracts_html_and_headers(self):
        payload = {
            "id": "abc",
            "internalDate": "1700000000000",
            "payload": {
                "mimeType": "multipart/alternative",
                "headers": [
                    {"name": "From", "value": "Lenny <lenny@substack.com>"},
                    {"name": "Subject", "value": "Weekly post"},
                ],
                "parts": [
                    {"mimeType": "text/plain", "body": {"data": _b64("plain text")}},
                    {"mimeType": "text/html", "body": {"data": _b64("<html>hi</html>")}},
                ],
            },
        }
        svc = _mock_service_with_messages([["abc"]], {"abc": payload})
        msg = _gmail_client.get_message("abc", service=svc)
        assert msg["id"] == "abc"
        assert msg["internal_date"] == "1700000000000"
        assert msg["headers"]["from"] == "Lenny <lenny@substack.com>"
        assert msg["headers"]["subject"] == "Weekly post"
        assert msg["html_body"] == "<html>hi</html>"
        assert msg["plain_body"] == "plain text"

    def test_handles_single_part(self):
        payload = {
            "id": "x",
            "internalDate": "0",
            "payload": {
                "mimeType": "text/html",
                "headers": [{"name": "Subject", "value": "S"}],
                "body": {"data": _b64("<p>body</p>")},
            },
        }
        svc = _mock_service_with_messages([["x"]], {"x": payload})
        msg = _gmail_client.get_message("x", service=svc)
        assert msg["html_body"] == "<p>body</p>"
        assert msg["plain_body"] == ""

    def test_handles_nested_parts(self):
        inner = {"mimeType": "text/html", "body": {"data": _b64("<p>nested</p>")}}
        payload = {
            "id": "y",
            "internalDate": "0",
            "payload": {
                "mimeType": "multipart/mixed",
                "headers": [],
                "parts": [{"mimeType": "multipart/alternative", "parts": [inner]}],
            },
        }
        svc = _mock_service_with_messages([["y"]], {"y": payload})
        msg = _gmail_client.get_message("y", service=svc)
        assert msg["html_body"] == "<p>nested</p>"


class TestFetchMessages:
    def test_combines_list_and_get(self):
        payloads = {
            "1": {"payload": {"headers": [], "body": {"data": _b64("a")}, "mimeType": "text/plain"}, "internalDate": "0"},
            "2": {"payload": {"headers": [], "body": {"data": _b64("b")}, "mimeType": "text/plain"}, "internalDate": "1"},
        }
        svc = _mock_service_with_messages([["1", "2"]], payloads)
        msgs = _gmail_client.fetch_messages("q", service=svc)
        assert [m["id"] for m in msgs] == ["1", "2"]
        assert msgs[0]["plain_body"] == "a"
        assert msgs[1]["plain_body"] == "b"


class TestBuildCredentials:
    @patch.dict("os.environ", {}, clear=True)
    def test_raises_when_env_missing(self):
        with pytest.raises(_gmail_client.GmailAuthError):
            _gmail_client._build_credentials()
