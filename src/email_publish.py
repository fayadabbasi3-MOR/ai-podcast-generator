import logging
import os
import smtplib
import time
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import TypedDict

import markdown as md_lib

logger = logging.getLogger(__name__)

SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 587
SEND_RETRY_DELAY_S = 30


class EmailSection(TypedDict):
    title: str
    url: str
    publication_or_provider: str
    summary: str
    key_takeaways: list[str]


class SmtpCreds(TypedDict):
    sender: str
    password: str
    recipient: str


def smtp_creds_from_env() -> SmtpCreds:
    """Pull SMTP credentials from environment. Raises if any are missing."""
    sender = os.environ.get("GMAIL_SENDER", "")
    password = os.environ.get("GMAIL_APP_PASSWORD", "")
    recipient = os.environ.get("NOTIFY_EMAIL", "")
    if not all([sender, password, recipient]):
        raise EnvironmentError(
            "Missing SMTP env vars: GMAIL_SENDER, GMAIL_APP_PASSWORD, NOTIFY_EMAIL"
        )
    return SmtpCreds(sender=sender, password=password, recipient=recipient)


def send_episode_email(
    podcast_name: str,
    week_ending: str,
    sections: list[EmailSection],
    aggregate: dict | None,
    action_items: list[dict] | None,
    episode_url: str,
    creds: SmtpCreds,
) -> None:
    """Render and send the weekly digest. Action items block omitted when
    action_items is None or empty."""
    markdown_body, html_body = _render(
        podcast_name=podcast_name,
        week_ending=week_ending,
        sections=sections,
        aggregate=aggregate,
        action_items=action_items,
        episode_url=episode_url,
    )
    subject = f"[Podcast] {podcast_name} — {week_ending}"
    _send_smtp(subject, html_body, markdown_body, creds)


def send_empty_week_email(podcast_name: str, week_ending: str, creds: SmtpCreds) -> None:
    subject = f"[Podcast] {podcast_name} — no newsletters this week"
    body = (
        f"# {podcast_name} — week of {week_ending}\n\n"
        "No newsletters this week. The pipeline ran clean — nothing in the inbox to process.\n"
    )
    html = md_lib.markdown(body)
    _send_smtp(subject, html, body, creds)


# ── Rendering ──────────────────────────────────────────────────────────


def _render(
    *,
    podcast_name: str,
    week_ending: str,
    sections: list[EmailSection],
    aggregate: dict | None,
    action_items: list[dict] | None,
    episode_url: str,
) -> tuple[str, str]:
    item_count = len(sections)
    item_word = "stories" if podcast_name.lower().startswith("ai industry") else "newsletters"

    parts: list[str] = []
    parts.append(f"# {podcast_name} — week of {week_ending}\n")
    parts.append(f"[Listen to the episode]({episode_url})\n" if episode_url else "")
    parts.append(f"## This week ({item_count} {item_word})\n")

    for sec in sections:
        title_line = f"### [{sec['title']}]({sec['url']})" if sec.get("url") else f"### {sec['title']}"
        provider = sec.get("publication_or_provider", "")
        if provider:
            title_line += f" — *{provider}*"
        parts.append(title_line)
        if sec.get("summary"):
            parts.append(sec["summary"])
        if sec.get("key_takeaways"):
            parts.append("**Key takeaways:**")
            for takeaway in sec["key_takeaways"]:
                parts.append(f"- {takeaway}")
        parts.append("")

    if aggregate and aggregate.get("narrative"):
        parts.append("## The bigger picture\n")
        parts.append(aggregate["narrative"])
        themes = aggregate.get("cross_cutting_themes") or []
        if themes:
            parts.append("\n**Themes this week:**")
            for theme in themes:
                parts.append(f"- {theme}")
        parts.append("")

    if action_items:
        parts.append("## Three things to do this week\n")
        for i, action in enumerate(action_items, start=1):
            line = (
                f"{i}. **{action['title']}** — {action['description']}"
                f" ([source]({action['source_url']})) · ~{action['estimated_minutes']} min"
            )
            parts.append(line)
        parts.append("")

    parts.append("---")
    parts.append(f"*Generated automatically for {week_ending}.*")

    markdown_body = "\n".join(p for p in parts if p is not None)
    html_body = md_lib.markdown(markdown_body, extensions=["extra"])
    return markdown_body, html_body


# ── Adapters ───────────────────────────────────────────────────────────


def sections_from_substack_summaries(per_item: list[dict]) -> list[EmailSection]:
    """Convert NewsletterSummary list → email sections."""
    return [
        EmailSection(
            title=s.get("title", "Untitled"),
            url=s.get("url", ""),
            publication_or_provider=s.get("publication", ""),
            summary=s.get("summary", ""),
            key_takeaways=list(s.get("key_takeaways") or []),
        )
        for s in per_item
    ]


def sections_from_ai_industry_themes(themes: list[dict]) -> list[EmailSection]:
    """Convert AI Industry themes → flat list of stories as sections.

    Each story under a theme becomes one section; the theme name lands in
    publication_or_provider with the provider name.
    """
    sections: list[EmailSection] = []
    for theme in themes or []:
        theme_name = theme.get("name", "")
        for item in theme.get("items") or []:
            provider = item.get("provider", "")
            label = f"{theme_name} · {provider}" if provider else theme_name
            sections.append(EmailSection(
                title=item.get("title", "Untitled"),
                url=item.get("url", ""),
                publication_or_provider=label,
                summary=item.get("summary", ""),
                key_takeaways=[],
            ))
    return sections


# ── Transport ──────────────────────────────────────────────────────────


def _send_smtp(subject: str, html_body: str, text_body: str, creds: SmtpCreds) -> None:
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = creds["sender"]
    msg["To"] = creds["recipient"]
    msg.attach(MIMEText(text_body, "plain"))
    msg.attach(MIMEText(html_body, "html"))

    last_error: Exception | None = None
    for attempt in range(2):
        try:
            with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
                server.starttls()
                server.login(creds["sender"], creds["password"])
                server.send_message(msg)
            logger.info("Email sent to %s (subject: %s)", creds["recipient"], subject)
            return
        except smtplib.SMTPException as e:
            last_error = e
            if attempt == 0:
                logger.warning("SMTP send failed (attempt 1/2): %s — retrying in %ds", e, SEND_RETRY_DELAY_S)
                time.sleep(SEND_RETRY_DELAY_S)
            else:
                logger.error("SMTP send failed twice: %s", e)

    raise RuntimeError(f"Email send failed after retry: {last_error}")
