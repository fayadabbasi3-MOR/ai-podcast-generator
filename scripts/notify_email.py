"""Send an email notification with the latest podcast episode URL."""

import logging
import os
import smtplib
import sys
from email.mime.text import MIMEText
from pathlib import Path

from lxml import etree

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

FEED_PATH = Path(__file__).resolve().parent.parent / "site" / "feed.xml"


def get_latest_episode(feed_path: Path) -> dict:
    """Parse feed.xml and return metadata for the most recent episode."""
    tree = etree.parse(str(feed_path))
    channel = tree.getroot().find("channel")
    item = channel.find("item")
    if item is None:
        raise ValueError("No episodes found in feed.xml")

    enclosure = item.find("enclosure")
    return {
        "title": item.findtext("title", ""),
        "url": enclosure.get("url", "") if enclosure is not None else "",
        "pub_date": item.findtext("pubDate", ""),
        "description": item.findtext("description", ""),
    }


def send_email(sender: str, password: str, recipient: str, episode: dict) -> None:
    """Send episode notification via Gmail SMTP."""
    feed_url = episode["url"].rsplit("/episodes/", 1)[0] + "/feed.xml"

    body = (
        f"A new podcast episode is available:\n\n"
        f"{episode['title']}\n\n"
        f"Listen: {episode['url']}\n\n"
        f"Feed: {feed_url}\n"
    )

    msg = MIMEText(body)
    msg["Subject"] = f"New Episode: {episode['title']}"
    msg["From"] = sender
    msg["To"] = recipient

    with smtplib.SMTP("smtp.gmail.com", 587) as server:
        server.starttls()
        server.login(sender, password)
        server.send_message(msg)

    logger.info("Email sent to %s", recipient)


def main() -> None:
    sender = os.environ.get("GMAIL_SENDER", "")
    password = os.environ.get("GMAIL_APP_PASSWORD", "")
    recipient = os.environ.get("NOTIFY_EMAIL", "")

    if not all([sender, password, recipient]):
        logger.error("Missing required env vars: GMAIL_SENDER, GMAIL_APP_PASSWORD, NOTIFY_EMAIL")
        sys.exit(1)

    if not FEED_PATH.exists():
        logger.error("Feed not found: %s", FEED_PATH)
        sys.exit(1)

    episode = get_latest_episode(FEED_PATH)
    logger.info("Latest episode: %s", episode["title"])

    send_email(sender, password, recipient, episode)


if __name__ == "__main__":
    main()
