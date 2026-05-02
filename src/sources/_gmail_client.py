import base64
import logging
import os
from typing import Iterator

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

logger = logging.getLogger(__name__)

GMAIL_SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]
GMAIL_TOKEN_URI = "https://oauth2.googleapis.com/token"


class GmailAuthError(RuntimeError):
    pass


def _build_credentials() -> Credentials:
    client_id = os.environ.get("GMAIL_OAUTH_CLIENT_ID", "")
    client_secret = os.environ.get("GMAIL_OAUTH_CLIENT_SECRET", "")
    refresh_token = os.environ.get("GMAIL_OAUTH_REFRESH_TOKEN", "")
    if not all([client_id, client_secret, refresh_token]):
        raise GmailAuthError(
            "Missing Gmail OAuth env vars: "
            "GMAIL_OAUTH_CLIENT_ID, GMAIL_OAUTH_CLIENT_SECRET, GMAIL_OAUTH_REFRESH_TOKEN"
        )
    creds = Credentials(
        token=None,
        refresh_token=refresh_token,
        token_uri=GMAIL_TOKEN_URI,
        client_id=client_id,
        client_secret=client_secret,
        scopes=GMAIL_SCOPES,
    )
    creds.refresh(Request())
    return creds


def _build_service(credentials: Credentials | None = None):
    creds = credentials or _build_credentials()
    return build("gmail", "v1", credentials=creds, cache_discovery=False)


def list_message_ids(query: str, service=None) -> Iterator[str]:
    svc = service or _build_service()
    page_token: str | None = None
    while True:
        kwargs = {"userId": "me", "q": query, "maxResults": 100}
        if page_token:
            kwargs["pageToken"] = page_token
        resp = svc.users().messages().list(**kwargs).execute()
        for msg in resp.get("messages", []):
            yield msg["id"]
        page_token = resp.get("nextPageToken")
        if not page_token:
            return


def get_message(msg_id: str, service=None) -> dict:
    svc = service or _build_service()
    msg = svc.users().messages().get(userId="me", id=msg_id, format="full").execute()

    headers = {h["name"].lower(): h["value"] for h in msg.get("payload", {}).get("headers", [])}
    html_body, plain_body = _extract_bodies(msg.get("payload", {}))

    return {
        "id": msg_id,
        "internal_date": msg.get("internalDate"),
        "headers": headers,
        "html_body": html_body,
        "plain_body": plain_body,
    }


def fetch_messages(query: str, service=None) -> list[dict]:
    svc = service or _build_service()
    return [get_message(mid, service=svc) for mid in list_message_ids(query, service=svc)]


def _extract_bodies(payload: dict) -> tuple[str, str]:
    html = ""
    plain = ""

    def walk(part: dict) -> None:
        nonlocal html, plain
        mime = part.get("mimeType", "")
        body = part.get("body", {})
        data = body.get("data")
        if data:
            decoded = _decode_b64url(data)
            if mime == "text/html" and not html:
                html = decoded
            elif mime == "text/plain" and not plain:
                plain = decoded
        for sub in part.get("parts", []) or []:
            walk(sub)

    walk(payload)
    return html, plain


def _decode_b64url(data: str) -> str:
    try:
        return base64.urlsafe_b64decode(data.encode("ascii")).decode("utf-8", errors="replace")
    except Exception as e:
        logger.warning("Gmail body decode failed: %s", e)
        return ""
