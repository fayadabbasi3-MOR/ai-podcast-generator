import logging
import shutil
from datetime import datetime, timezone
from email.utils import formatdate
from pathlib import Path

from lxml import etree

from src.audio import format_duration_itunes, get_mp3_duration_seconds
from src.config import (
    EPISODES_DIR,
    PAGES_BASE_URL,
    PODCAST_AUTHOR,
    PODCAST_DESCRIPTION,
    PODCAST_EMAIL,
    PODCAST_TITLE,
    ROOT_DIR,
    SITE_DIR,
)

logger = logging.getLogger(__name__)

ITUNES_NS = "http://www.itunes.com/dtds/podcast-1.0.dtd"
ATOM_NS = "http://www.w3.org/2005/Atom"
NSMAP = {
    "itunes": ITUNES_NS,
    "atom": ATOM_NS,
    "content": "http://purl.org/rss/1.0/modules/content/",
}
TEMPLATE_PATH = ROOT_DIR / "templates" / "feed_template.xml"


def get_episode_metadata(
    mp3_path: Path,
    pages_base_url: str,
    podcast_title: str = PODCAST_TITLE,
    episode_url_subpath: str = "episodes",
    guid_prefix: str = "episode",
) -> dict:
    """Build metadata dict for an episode.

    podcast_title: drives the per-episode title and description prefix.
    episode_url_subpath: where the MP3 is reachable under pages_base_url
        (e.g. "episodes" for AI Industry, "substack/episodes" for Substack).
    guid_prefix: stable prefix for episode GUIDs; varied across podcasts so
        the same date doesn't collide across feeds.
    """
    now = datetime.now(timezone.utc)
    date_str = now.strftime("%Y-%m-%d")
    file_name = f"episode_{date_str}.mp3"
    size_bytes = mp3_path.stat().st_size
    duration_s = get_mp3_duration_seconds(mp3_path)

    return {
        "title": f"{podcast_title} — {now.strftime('%B %-d, %Y')}",
        "file_name": file_name,
        "url": f"{pages_base_url}/{episode_url_subpath.strip('/')}/{file_name}",
        "size_bytes": size_bytes,
        "duration": format_duration_itunes(duration_s),
        "pub_date": formatdate(now.timestamp(), usegmt=True),
        "description": f"{podcast_title} episode for the week ending {date_str}.",
        "guid": f"{guid_prefix}_{date_str}",
    }


def create_episode_item(metadata: dict) -> etree._Element:
    """Build an RSS <item> element with iTunes extensions."""
    item = etree.Element("item")

    title = etree.SubElement(item, "title")
    title.text = metadata["title"]

    description = etree.SubElement(item, "description")
    description.text = metadata["description"]

    etree.SubElement(
        item,
        "enclosure",
        url=metadata["url"],
        length=str(metadata["size_bytes"]),
        type="audio/mpeg",
    )

    guid = etree.SubElement(item, "guid", isPermaLink="false")
    guid.text = metadata["guid"]

    pub_date = etree.SubElement(item, "pubDate")
    pub_date.text = metadata["pub_date"]

    duration = etree.SubElement(item, f"{{{ITUNES_NS}}}duration")
    duration.text = metadata["duration"]

    summary = etree.SubElement(item, f"{{{ITUNES_NS}}}summary")
    summary.text = metadata["description"]

    episode_type = etree.SubElement(item, f"{{{ITUNES_NS}}}episodeType")
    episode_type.text = "full"

    return item


def update_feed(
    feed_path: Path,
    new_item: etree._Element,
    channel_config: dict | None = None,
) -> None:
    """Parse existing feed.xml, insert new <item> as the first child of <channel>
    (after the channel metadata elements), and write back.

    channel_config: optional dict of overrides used when bootstrapping the
        template AND when syncing channel-level metadata. Defaults to AI
        Industry settings derived from src.config.
    """
    config = channel_config or _default_channel_config(feed_path)

    if not feed_path.exists():
        create_initial_feed(TEMPLATE_PATH, feed_path, config)

    parser = etree.XMLParser(remove_blank_text=True)
    tree = etree.parse(str(feed_path), parser)
    root = tree.getroot()
    channel = root.find("channel")

    _sync_channel_metadata(channel, config)

    # Find insertion point: after last non-item child of channel
    insert_idx = 0
    for i, child in enumerate(channel):
        if child.tag == "item":
            insert_idx = i
            break
    else:
        insert_idx = len(channel)

    channel.insert(insert_idx, new_item)

    tree.write(
        str(feed_path),
        xml_declaration=True,
        encoding="UTF-8",
        pretty_print=True,
    )


def create_initial_feed(
    template_path: Path, output_path: Path, config: dict
) -> None:
    """Bootstrap a new feed.xml from the template, filling in config placeholders."""
    output_path.parent.mkdir(parents=True, exist_ok=True)

    content = template_path.read_text()
    for key, value in config.items():
        content = content.replace(f"{{{key}}}", value)

    output_path.write_text(content)
    logger.info("Created initial feed at %s", output_path)


def _default_channel_config(feed_path: Path) -> dict:
    feed_self_url = f"{PAGES_BASE_URL}/{feed_path.name}" if PAGES_BASE_URL else ""
    return {
        "PAGES_BASE_URL": PAGES_BASE_URL,
        "PODCAST_TITLE": PODCAST_TITLE,
        "PODCAST_DESCRIPTION": PODCAST_DESCRIPTION,
        "PODCAST_AUTHOR": PODCAST_AUTHOR,
        "PODCAST_EMAIL": PODCAST_EMAIL,
        "FEED_SELF_URL": feed_self_url,
    }


def _sync_channel_metadata(channel: etree._Element, config: dict) -> None:
    """Update channel-level metadata fields to match current config values."""
    itunes = f"{{{ITUNES_NS}}}"
    author = config.get("PODCAST_AUTHOR", PODCAST_AUTHOR)
    email = config.get("PODCAST_EMAIL", PODCAST_EMAIL)

    field_map = {
        f"{itunes}author": author,
        f"{itunes}email": email,
    }
    for tag, value in field_map.items():
        el = channel.find(tag)
        if el is not None:
            el.text = value
        else:
            el = etree.SubElement(channel, tag)
            el.text = value

    owner = channel.find(f"{itunes}owner")
    if owner is not None:
        name_el = owner.find(f"{itunes}name")
        if name_el is not None:
            name_el.text = author
        email_el = owner.find(f"{itunes}email")
        if email_el is not None:
            email_el.text = email
