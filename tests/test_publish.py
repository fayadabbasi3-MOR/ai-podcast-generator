import shutil
from pathlib import Path

import pytest
from lxml import etree

from src.publish import (
    create_episode_item,
    create_initial_feed,
    get_episode_metadata,
    update_feed,
    ITUNES_NS,
    TEMPLATE_PATH,
)


# ── Fixtures ───────────────────────────────────────────


ITUNES = {"itunes": ITUNES_NS}

SAMPLE_METADATA = {
    "title": "AI Industry Weekly — March 5, 2025",
    "file_name": "episode_2025-03-05.mp3",
    "url": "https://user.github.io/repo/episodes/episode_2025-03-05.mp3",
    "size_bytes": 4823040,
    "duration": "00:08:32",
    "pub_date": "Wed, 05 Mar 2025 20:00:00 GMT",
    "description": "This week: Claude 4.5 Haiku launches.",
    "guid": "episode_2025-03-05",
}


def _make_feed_xml(tmp_path: Path) -> Path:
    """Create a valid feed.xml in tmp_path from the template."""
    feed_path = tmp_path / "feed.xml"
    create_initial_feed(
        TEMPLATE_PATH,
        feed_path,
        {
            "PAGES_BASE_URL": "https://example.github.io/podcast",
            "PODCAST_AUTHOR": "Test Author",
            "PODCAST_EMAIL": "test@example.com",
        },
    )
    return feed_path


# ── get_episode_metadata ───────────────────────────────


class TestGetEpisodeMetadata:
    def test_returns_all_fields(self, tmp_path):
        """Metadata dict has all required keys."""
        mp3 = tmp_path / "episode.mp3"
        mp3.write_bytes(b"\x00" * 1_000_000)

        meta = get_episode_metadata(mp3, "https://example.github.io/pod")

        assert "title" in meta
        assert "file_name" in meta
        assert "url" in meta
        assert "size_bytes" in meta
        assert meta["size_bytes"] == 1_000_000
        assert "duration" in meta
        assert "pub_date" in meta
        assert "description" in meta
        assert "guid" in meta

    def test_url_includes_base(self, tmp_path):
        """URL is constructed from base URL + episodes/ + filename."""
        mp3 = tmp_path / "episode.mp3"
        mp3.write_bytes(b"\x00" * 100)

        meta = get_episode_metadata(mp3, "https://example.github.io/pod")

        assert meta["url"].startswith("https://example.github.io/pod/episodes/")


# ── create_episode_item ────────────────────────────────


class TestCreateEpisodeItem:
    def test_has_required_elements(self):
        """Item has title, enclosure, guid, pubDate, itunes:duration."""
        item = create_episode_item(SAMPLE_METADATA)

        assert item.findtext("title") == SAMPLE_METADATA["title"]
        assert item.findtext("description") == SAMPLE_METADATA["description"]
        assert item.findtext("pubDate") == SAMPLE_METADATA["pub_date"]

        guid = item.find("guid")
        assert guid.text == SAMPLE_METADATA["guid"]
        assert guid.get("isPermaLink") == "false"

        enclosure = item.find("enclosure")
        assert enclosure is not None
        assert enclosure.get("url") == SAMPLE_METADATA["url"]
        assert enclosure.get("type") == "audio/mpeg"

        assert item.findtext(f"{{{ITUNES_NS}}}duration") == SAMPLE_METADATA["duration"]
        assert item.findtext(f"{{{ITUNES_NS}}}episodeType") == "full"
        assert item.findtext(f"{{{ITUNES_NS}}}summary") == SAMPLE_METADATA["description"]

    def test_enclosure_length_matches_file_size(self):
        """Length attribute equals actual file size in bytes."""
        item = create_episode_item(SAMPLE_METADATA)

        enclosure = item.find("enclosure")
        assert enclosure.get("length") == str(SAMPLE_METADATA["size_bytes"])


# ── update_feed ────────────────────────────────────────


class TestUpdateFeed:
    def test_inserts_item_first(self, tmp_path):
        """New item is first <item> in channel (most recent episode first)."""
        feed_path = _make_feed_xml(tmp_path)

        # Insert first episode
        item1 = create_episode_item({**SAMPLE_METADATA, "guid": "episode_2025-03-01", "title": "Episode 1"})
        update_feed(feed_path, item1)

        # Insert second episode
        item2 = create_episode_item({**SAMPLE_METADATA, "guid": "episode_2025-03-08", "title": "Episode 2"})
        update_feed(feed_path, item2)

        tree = etree.parse(str(feed_path))
        items = tree.findall(".//item")
        assert len(items) == 2
        # Most recent episode should be first
        assert items[0].findtext("title") == "Episode 2"
        assert items[1].findtext("title") == "Episode 1"

    def test_creates_from_template_if_missing(self, tmp_path):
        """If feed.xml doesn't exist, bootstrap from template."""
        feed_path = tmp_path / "site" / "feed.xml"
        assert not feed_path.exists()

        item = create_episode_item(SAMPLE_METADATA)

        # Patch config values so create_initial_feed uses them
        from unittest.mock import patch
        with patch("src.publish.PAGES_BASE_URL", "https://test.github.io/pod"), \
             patch("src.publish.PODCAST_AUTHOR", "Test"), \
             patch("src.publish.PODCAST_EMAIL", "test@test.com"):
            update_feed(feed_path, item)

        assert feed_path.exists()
        tree = etree.parse(str(feed_path))
        channel = tree.find(".//channel")
        assert channel.findtext("title") == "AI Industry Weekly"
        items = tree.findall(".//item")
        assert len(items) == 1

    def test_preserves_xml_declaration(self, tmp_path):
        """Output file has XML declaration with UTF-8 encoding."""
        feed_path = _make_feed_xml(tmp_path)
        item = create_episode_item(SAMPLE_METADATA)
        update_feed(feed_path, item)

        content = feed_path.read_text()
        assert content.startswith("<?xml version=")
        assert "UTF-8" in content.split("\n")[0]


# ── create_initial_feed ────────────────────────────────


class TestCreateInitialFeed:
    def test_replaces_placeholders(self, tmp_path):
        """Template placeholders are replaced with config values."""
        feed_path = tmp_path / "feed.xml"
        create_initial_feed(
            TEMPLATE_PATH,
            feed_path,
            {
                "PAGES_BASE_URL": "https://mysite.github.io/podcast",
                "PODCAST_AUTHOR": "Jane Doe",
                "PODCAST_EMAIL": "jane@example.com",
            },
        )

        content = feed_path.read_text()
        assert "https://mysite.github.io/podcast" in content
        assert "Jane Doe" in content
        assert "jane@example.com" in content
        assert "{PAGES_BASE_URL}" not in content
        assert "{PODCAST_AUTHOR}" not in content
        assert "{PODCAST_EMAIL}" not in content

    def test_creates_parent_dirs(self, tmp_path):
        """Parent directories are created if they don't exist."""
        feed_path = tmp_path / "nested" / "deep" / "feed.xml"
        create_initial_feed(
            TEMPLATE_PATH,
            feed_path,
            {"PAGES_BASE_URL": "x", "PODCAST_AUTHOR": "y", "PODCAST_EMAIL": "z"},
        )

        assert feed_path.exists()


# ── Metadata sync ─────────────────────────────────────


class TestMetadataSync:
    def test_update_feed_syncs_author_and_email(self, tmp_path):
        """update_feed overwrites channel metadata even if feed was created with empty values."""
        # Create feed with empty author/email (simulates the original bug)
        feed_path = tmp_path / "feed.xml"
        create_initial_feed(
            TEMPLATE_PATH,
            feed_path,
            {"PAGES_BASE_URL": "https://test.io", "PODCAST_AUTHOR": "", "PODCAST_EMAIL": ""},
        )

        # Verify they're empty
        tree = etree.parse(str(feed_path))
        channel = tree.find(".//channel")
        assert channel.findtext(f"{{{ITUNES_NS}}}author") == ""

        # Now call update_feed with config values set
        item = create_episode_item(SAMPLE_METADATA)
        from unittest.mock import patch
        with patch("src.publish.PODCAST_AUTHOR", "Fixed Author"), \
             patch("src.publish.PODCAST_EMAIL", "fixed@example.com"):
            update_feed(feed_path, item)

        # Verify metadata was synced
        tree = etree.parse(str(feed_path))
        channel = tree.find(".//channel")
        assert channel.findtext(f"{{{ITUNES_NS}}}author") == "Fixed Author"
        assert channel.findtext(f"{{{ITUNES_NS}}}email") == "fixed@example.com"

        owner = channel.find(f"{{{ITUNES_NS}}}owner")
        assert owner.findtext(f"{{{ITUNES_NS}}}name") == "Fixed Author"
        assert owner.findtext(f"{{{ITUNES_NS}}}email") == "fixed@example.com"


# ── Cross-file consistency ────────────────────────────


class TestWorkflowConsistency:
    def test_gitignore_does_not_block_workflow_git_add(self):
        """Every file the workflow git-adds must use -f if matched by .gitignore."""
        import re
        from pathlib import Path
        from fnmatch import fnmatch

        root = Path(__file__).resolve().parent.parent
        gitignore_path = root / ".gitignore"
        workflow_path = root / ".github" / "workflows" / "generate-episode.yml"

        if not gitignore_path.exists() or not workflow_path.exists():
            pytest.skip("Missing .gitignore or workflow file")

        # Parse gitignore patterns
        patterns = []
        for line in gitignore_path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                patterns.append(line.rstrip("/"))

        # Extract all 'git add' commands from workflow
        workflow = workflow_path.read_text()
        git_add_lines = re.findall(r"git add\s+(.*)", workflow)

        for line in git_add_lines:
            has_force = "-f" in line
            # Extract paths (skip flags)
            paths = [p for p in line.split() if not p.startswith("-")]

            for path in paths:
                for pattern in patterns:
                    # Check if any component of the path matches a gitignore pattern
                    path_parts = path.rstrip("/").split("/")
                    for part in path_parts:
                        if fnmatch(part, pattern) or fnmatch(part + "/", pattern + "/"):
                            assert has_force, (
                                f"Workflow 'git add {path}' matches .gitignore pattern "
                                f"'{pattern}' but does not use -f flag"
                            )
