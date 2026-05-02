import smtplib
from unittest.mock import MagicMock, patch

import pytest

from src.email_publish import (
    EmailSection,
    SmtpCreds,
    _render,
    _send_smtp,
    sections_from_ai_industry_themes,
    sections_from_substack_summaries,
    send_empty_week_email,
    send_episode_email,
    smtp_creds_from_env,
)


def _creds() -> SmtpCreds:
    return SmtpCreds(sender="me@gmail.com", password="apppass", recipient="me@gmail.com")


def _section(title="Build vs Buy", url="https://l.com/p/x") -> EmailSection:
    return EmailSection(
        title=title,
        url=url,
        publication_or_provider="Lenny",
        summary="The post argues most teams misuse the build-vs-buy framework.",
        key_takeaways=["Buy non-core", "Build core"],
    )


def _aggregate() -> dict:
    return {
        "narrative": "This week's newsletters all converge on one theme.",
        "cross_cutting_themes": ["build vs buy", "team capacity"],
        "notable_quotes": [],
    }


def _actions(url="https://l.com/p/x") -> list[dict]:
    return [
        {"title": f"Action {i}", "description": "Do thing", "source_url": url, "estimated_minutes": 15}
        for i in range(1, 4)
    ]


# ── Render ─────────────────────────────────────────────────────────────


class TestRender:
    def test_substack_email_includes_all_blocks(self):
        md, html = _render(
            podcast_name="Substack PM Weekly",
            week_ending="2026-05-08",
            sections=[_section()],
            aggregate=_aggregate(),
            action_items=_actions(),
            episode_url="https://example.com/sub/ep.mp3",
        )
        assert "Substack PM Weekly — week of 2026-05-08" in md
        assert "Listen to the episode" in md
        assert "Build vs Buy" in md
        assert "Lenny" in md
        assert "The bigger picture" in md
        assert "Three things to do this week" in md
        assert "<h1>" in html
        assert "<a href=\"https://example.com/sub/ep.mp3\">" in html

    def test_ai_industry_email_omits_action_items(self):
        md, _ = _render(
            podcast_name="AI Industry Weekly",
            week_ending="2026-05-08",
            sections=[_section(title="Claude 4 Released", url="https://anthropic.com/x")],
            aggregate=None,
            action_items=None,
            episode_url="https://example.com/ai/ep.mp3",
        )
        assert "Three things to do this week" not in md
        assert "The bigger picture" not in md
        assert "Claude 4 Released" in md
        assert "stories" in md  # AI Industry uses 'stories' not 'newsletters'

    def test_substack_uses_newsletters_word(self):
        md, _ = _render(
            podcast_name="Substack PM Weekly",
            week_ending="2026-05-08",
            sections=[_section()],
            aggregate=None,
            action_items=None,
            episode_url="",
        )
        assert "newsletters" in md
        assert "stories" not in md.lower().replace("newsletters", "")

    def test_action_items_render_with_estimated_minutes(self):
        md, _ = _render(
            podcast_name="Substack PM Weekly",
            week_ending="2026-05-08",
            sections=[_section()],
            aggregate=_aggregate(),
            action_items=_actions(),
            episode_url="https://x.com",
        )
        assert "~15 min" in md
        assert "[source]" in md

    def test_empty_action_items_omits_block(self):
        md, _ = _render(
            podcast_name="Substack PM Weekly",
            week_ending="2026-05-08",
            sections=[_section()],
            aggregate=None,
            action_items=[],
            episode_url="",
        )
        assert "Three things to do this week" not in md


# ── Adapters ───────────────────────────────────────────────────────────


class TestAdapters:
    def test_sections_from_substack(self):
        per_item = [
            {
                "title": "Build vs Buy",
                "url": "https://l.com/p/x",
                "publication": "Lenny",
                "summary": "x",
                "key_takeaways": ["a", "b"],
            }
        ]
        sections = sections_from_substack_summaries(per_item)
        assert len(sections) == 1
        assert sections[0]["publication_or_provider"] == "Lenny"
        assert sections[0]["key_takeaways"] == ["a", "b"]

    def test_sections_from_ai_industry_themes_flattens_items(self):
        themes = [
            {
                "name": "Models",
                "items": [
                    {"title": "Claude 4", "url": "https://x", "summary": "s", "provider": "anthropic"},
                    {"title": "GPT-5", "url": "https://y", "summary": "s2", "provider": "openai"},
                ],
            },
            {"name": "API", "items": [{"title": "New", "url": "https://z", "summary": "s3", "provider": "gemini"}]},
        ]
        sections = sections_from_ai_industry_themes(themes)
        assert len(sections) == 3
        assert sections[0]["publication_or_provider"].startswith("Models")
        assert "anthropic" in sections[0]["publication_or_provider"]

    def test_sections_from_empty_themes(self):
        assert sections_from_ai_industry_themes([]) == []
        assert sections_from_ai_industry_themes(None) == []


# ── SMTP transport ─────────────────────────────────────────────────────


class TestSendSmtp:
    @patch("src.email_publish.smtplib.SMTP")
    def test_sends_multipart_alternative(self, mock_smtp):
        server = MagicMock()
        mock_smtp.return_value.__enter__.return_value = server

        _send_smtp("Subject", "<p>html</p>", "plain text", _creds())

        server.starttls.assert_called_once()
        server.login.assert_called_once_with("me@gmail.com", "apppass")
        server.send_message.assert_called_once()
        msg = server.send_message.call_args.args[0]
        assert msg["Subject"] == "Subject"
        assert msg["From"] == "me@gmail.com"
        assert msg["To"] == "me@gmail.com"
        # both plain and html parts present
        parts = msg.get_payload()
        types = [p.get_content_type() for p in parts]
        assert "text/plain" in types
        assert "text/html" in types

    @patch("src.email_publish.time.sleep")
    @patch("src.email_publish.smtplib.SMTP")
    def test_retries_once_on_smtp_exception(self, mock_smtp, mock_sleep):
        server = MagicMock()
        mock_smtp.return_value.__enter__.return_value = server
        server.send_message.side_effect = [smtplib.SMTPException("transient"), None]

        _send_smtp("S", "<p>h</p>", "p", _creds())

        assert server.send_message.call_count == 2
        mock_sleep.assert_called_once()

    @patch("src.email_publish.time.sleep")
    @patch("src.email_publish.smtplib.SMTP")
    def test_raises_after_retry_exhausted(self, mock_smtp, mock_sleep):
        server = MagicMock()
        mock_smtp.return_value.__enter__.return_value = server
        server.send_message.side_effect = smtplib.SMTPException("dead")

        with pytest.raises(RuntimeError, match="Email send failed"):
            _send_smtp("S", "<p>h</p>", "p", _creds())

        assert server.send_message.call_count == 2


# ── Top-level send ─────────────────────────────────────────────────────


class TestSendEpisodeEmail:
    @patch("src.email_publish._send_smtp")
    def test_substack_subject_and_payload(self, mock_send):
        send_episode_email(
            podcast_name="Substack PM Weekly",
            week_ending="2026-05-08",
            sections=[_section()],
            aggregate=_aggregate(),
            action_items=_actions(),
            episode_url="https://x.com/ep",
            creds=_creds(),
        )
        args = mock_send.call_args.args
        subject, html, text, _creds_arg = args
        assert subject == "[Podcast] Substack PM Weekly — 2026-05-08"
        assert "Three things to do this week" in text
        assert "<h2>" in html

    @patch("src.email_publish._send_smtp")
    def test_ai_industry_no_actions(self, mock_send):
        send_episode_email(
            podcast_name="AI Industry Weekly",
            week_ending="2026-05-08",
            sections=[_section(title="Claude 4")],
            aggregate=None,
            action_items=None,
            episode_url="https://x.com/ep",
            creds=_creds(),
        )
        _, html, text, _ = mock_send.call_args.args
        assert "Three things" not in text


class TestSendEmptyWeek:
    @patch("src.email_publish._send_smtp")
    def test_subject_and_body(self, mock_send):
        send_empty_week_email("Substack PM Weekly", "2026-05-08", _creds())
        subject, html, text, _ = mock_send.call_args.args
        assert subject == "[Podcast] Substack PM Weekly — no newsletters this week"
        assert "no newsletters" in text.lower()


# ── Env loader ─────────────────────────────────────────────────────────


class TestSmtpCredsFromEnv:
    @patch.dict("os.environ", {
        "GMAIL_SENDER": "a@b.com",
        "GMAIL_APP_PASSWORD": "p",
        "NOTIFY_EMAIL": "c@d.com",
    }, clear=True)
    def test_loads_when_all_present(self):
        creds = smtp_creds_from_env()
        assert creds["sender"] == "a@b.com"
        assert creds["password"] == "p"
        assert creds["recipient"] == "c@d.com"

    @patch.dict("os.environ", {"GMAIL_SENDER": "a@b.com"}, clear=True)
    def test_raises_when_missing(self):
        with pytest.raises(EnvironmentError):
            smtp_creds_from_env()
