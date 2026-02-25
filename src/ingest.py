import logging
from datetime import datetime, timedelta, timezone

import feedparser
import requests
from bs4 import BeautifulSoup
from lxml import etree

from src.config import ANTHROPIC_API_KEY
from src.diff import diff_models, diff_scrape, diff_sitemap

logger = logging.getLogger(__name__)

USER_AGENT = "AIPodcastBot/1.0"
REQUEST_TIMEOUT = 30
MAX_SITEMAP_ITEMS = 100  # Safety cap per sitemap source


def fetch_rss(url: str, since_days: int = 7) -> list[dict]:
    """Parse an RSS feed and return items published within `since_days`.

    Uses feedparser. Each returned dict is a ContentItem.
    Returns empty list on any failure (logged as warning).
    """
    try:
        feed = feedparser.parse(url)
        if feed.bozo and not feed.entries:
            logger.warning("RSS parse error for %s: %s", url, feed.bozo_exception)
            return []

        cutoff = datetime.now(timezone.utc) - timedelta(days=since_days)
        items = []
        for entry in feed.entries:
            published = _parse_feed_date(entry)
            if published and published < cutoff:
                continue

            items.append({
                "title": entry.get("title", ""),
                "url": entry.get("link", ""),
                "summary": _truncate(
                    entry.get("summary", entry.get("description", "")), 500
                ),
                "published": published.isoformat() if published else datetime.now(timezone.utc).isoformat(),
                "source_name": "",  # filled by ingest_all
                "provider": "",     # filled by ingest_all
                "method": "rss",
            })
        return items
    except Exception as e:
        logger.warning("Failed to fetch RSS %s: %s", url, e)
        return []


def fetch_atom(url: str, since_days: int = 7) -> list[dict]:
    """Parse an Atom feed and return entries published within `since_days`.

    Same return format as fetch_rss. GitHub Atom feeds use <updated> not <published>.
    """
    try:
        feed = feedparser.parse(url)
        if feed.bozo and not feed.entries:
            logger.warning("Atom parse error for %s: %s", url, feed.bozo_exception)
            return []

        cutoff = datetime.now(timezone.utc) - timedelta(days=since_days)
        items = []
        for entry in feed.entries:
            # GitHub Atom feeds use 'updated' rather than 'published'
            published = _parse_feed_date(entry)
            if published and published < cutoff:
                continue

            content = ""
            if hasattr(entry, "content") and entry.content:
                content = entry.content[0].get("value", "")
            elif hasattr(entry, "summary"):
                content = entry.summary or ""

            items.append({
                "title": entry.get("title", ""),
                "url": entry.get("link", ""),
                "summary": _truncate(content, 500),
                "published": published.isoformat() if published else datetime.now(timezone.utc).isoformat(),
                "source_name": "",
                "provider": "",
                "method": "atom",
            })
        return items
    except Exception as e:
        logger.warning("Failed to fetch Atom %s: %s", url, e)
        return []


def scrape_page(url: str, css_selector: str) -> str:
    """Fetch a page with requests, extract text via BeautifulSoup + css_selector.

    Returns the extracted text as a string.
    Raises on HTTP errors (caller handles).
    """
    resp = requests.get(
        url, headers={"User-Agent": USER_AGENT}, timeout=REQUEST_TIMEOUT
    )
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "lxml")
    elements = soup.select(css_selector)
    return "\n".join(el.get_text(separator=" ", strip=True) for el in elements)


def fetch_sitemap(url: str) -> dict[str, str | None]:
    """Parse a sitemap XML and return {url: lastmod_or_None} dict.

    Handles sitemap index files (recursive fetch of child sitemaps).
    """
    resp = requests.get(
        url, headers={"User-Agent": USER_AGENT}, timeout=REQUEST_TIMEOUT
    )
    resp.raise_for_status()

    root = etree.fromstring(resp.content)
    ns = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}

    # Check if this is a sitemap index
    sitemaps = root.findall("sm:sitemap", ns)
    if sitemaps:
        result = {}
        for sitemap in sitemaps:
            loc = sitemap.findtext("sm:loc", namespaces=ns)
            if loc:
                try:
                    result.update(fetch_sitemap(loc))
                except Exception as e:
                    logger.warning("Failed to fetch child sitemap %s: %s", loc, e)
        return result

    # Regular sitemap
    urls = {}
    for url_elem in root.findall("sm:url", ns):
        loc = url_elem.findtext("sm:loc", namespaces=ns)
        lastmod = url_elem.findtext("sm:lastmod", namespaces=ns)
        if loc:
            urls[loc] = lastmod
    return urls


def fetch_anthropic_models(api_key: str) -> list[dict]:
    """Call GET https://api.anthropic.com/v1/models with the API key.

    Returns list of model dicts (id, display_name, created_at).
    """
    resp = requests.get(
        "https://api.anthropic.com/v1/models",
        headers={
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
        },
        timeout=REQUEST_TIMEOUT,
    )
    resp.raise_for_status()
    data = resp.json()
    return [
        {
            "id": m["id"],
            "display_name": m.get("display_name", m["id"]),
            "created_at": m.get("created_at", ""),
        }
        for m in data.get("data", [])
    ]


def ingest_all(sources: list[dict], since_days: int = 7) -> dict:
    """Iterate over all enabled sources, dispatch to the correct fetcher,
    and return grouped results.

    Per-source try/except — log warning, append to errors, continue.
    """
    output: dict = {
        "anthropic": [],
        "openai": [],
        "gemini": [],
        "errors": [],
    }

    for source in sources:
        if not source.get("enabled", True):
            continue

        name = source["name"]
        provider = source["provider"]
        method = source["method"]
        url = source["url"]

        try:
            if method == "rss":
                items = fetch_rss(url, since_days)
            elif method == "atom":
                items = fetch_atom(url, since_days)
            elif method == "scrape":
                text = scrape_page(url, source.get("css_selector", "body"))
                if not text.strip():
                    items = []
                else:
                    # Diff against previous snapshot — None means unchanged
                    try:
                        diffed = diff_scrape(name, text)
                    except Exception as e:
                        logger.warning("Diff failed for %s, using raw text: %s", name, e)
                        diffed = text
                    if diffed is None:
                        items = []
                    else:
                        items = [
                            {
                                "title": name,
                                "url": url,
                                "summary": _truncate(diffed, 500),
                                "published": datetime.now(timezone.utc).isoformat(),
                                "source_name": name,
                                "provider": provider,
                                "method": "scrape",
                            }
                        ]
            elif method == "sitemap":
                url_map = fetch_sitemap(url)
                # Diff against previous snapshot — only new/changed URLs
                try:
                    new_urls = diff_sitemap(name, url_map)
                except Exception as e:
                    logger.warning("Diff failed for %s, using date filter only: %s", name, e)
                    new_urls = list(url_map.keys())

                # Filter by lastmod date (within since_days)
                cutoff = datetime.now(timezone.utc) - timedelta(days=since_days)
                items = []
                for u in new_urls:
                    lastmod = url_map.get(u)
                    if lastmod:
                        parsed_dt = _parse_lastmod(lastmod)
                        if parsed_dt and parsed_dt < cutoff:
                            continue
                    else:
                        # No lastmod — skip if no snapshot exists (first run)
                        # Diff already handled subsequent runs
                        continue

                    items.append({
                        "title": u.split("/")[-1] or u,
                        "url": u,
                        "summary": "",
                        "published": lastmod or datetime.now(timezone.utc).isoformat(),
                        "source_name": name,
                        "provider": provider,
                        "method": "sitemap",
                    })

                # Safety cap
                if len(items) > MAX_SITEMAP_ITEMS:
                    logger.warning(
                        "Capping %s from %d to %d items",
                        name, len(items), MAX_SITEMAP_ITEMS,
                    )
                    items = items[:MAX_SITEMAP_ITEMS]
            elif method == "api":
                models = fetch_anthropic_models(ANTHROPIC_API_KEY)
                # Diff against previous snapshot — only new models
                try:
                    new_models = diff_models(name, models)
                except Exception as e:
                    logger.warning("Diff failed for %s, using all models: %s", name, e)
                    new_models = models
                items = [
                    {
                        "title": m["display_name"],
                        "url": url,
                        "summary": f"Model {m['id']} (created {m.get('created_at', 'unknown')})",
                        "published": m.get("created_at", datetime.now(timezone.utc).isoformat()),
                        "source_name": name,
                        "provider": provider,
                        "method": "api",
                    }
                    for m in new_models
                ]
            else:
                logger.warning("Unknown method '%s' for source %s", method, name)
                continue

            # Stamp source_name and provider on rss/atom items
            for item in items:
                if not item["source_name"]:
                    item["source_name"] = name
                if not item["provider"]:
                    item["provider"] = provider

            output[provider].extend(items)
            logger.info("Source %s: %d items", name, len(items))

        except Exception as e:
            logger.warning("Source %s failed: %s", name, e)
            output["errors"].append({"source": name, "error": str(e)})

    return output


# ── Helpers ────────────────────────────────────────────


def _parse_feed_date(entry) -> datetime | None:
    """Extract a timezone-aware datetime from a feedparser entry."""
    for field in ("published_parsed", "updated_parsed"):
        tp = getattr(entry, field, None)
        if tp:
            try:
                from calendar import timegm
                return datetime.fromtimestamp(timegm(tp), tz=timezone.utc)
            except (ValueError, OverflowError):
                continue
    return None


def _parse_lastmod(lastmod: str) -> datetime | None:
    """Parse a sitemap lastmod string into a timezone-aware datetime."""
    try:
        s = lastmod.strip()
        # Handle "2026-02-25" (date only)
        if len(s) == 10:
            s += "T00:00:00+00:00"
        # Handle "Z" suffix
        s = s.replace("Z", "+00:00")
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (ValueError, AttributeError):
        return None


def _truncate(text: str, max_chars: int) -> str:
    """Truncate text to max_chars, stripping HTML tags first."""
    # Strip HTML tags if present
    if "<" in text and ">" in text:
        text = BeautifulSoup(text, "lxml").get_text(separator=" ", strip=True)
    if len(text) <= max_chars:
        return text
    return text[:max_chars].rsplit(" ", 1)[0] + "..."
