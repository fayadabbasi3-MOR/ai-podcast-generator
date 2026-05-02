import logging
import re

from bs4 import BeautifulSoup
from readability import Document

logger = logging.getLogger(__name__)

MIN_BODY_CHARS = 500

CHROME_PATTERNS = [
    re.compile(r"\bunsubscribe\b", re.IGNORECASE),
    re.compile(r"\bmanage (your )?subscription\b", re.IGNORECASE),
    re.compile(r"\bview in browser\b", re.IGNORECASE),
    re.compile(r"\bget the app\b", re.IGNORECASE),
]

SUBSTACK_POST_RE = re.compile(r"https?://[^\s\"'<>]+/p/[A-Za-z0-9\-_]+", re.IGNORECASE)
SUBSTACK_DOMAIN_RE = re.compile(r"https?://[a-z0-9\-]+\.substack\.com/[^\s\"'<>]*", re.IGNORECASE)


class BodyTooShort(ValueError):
    pass


def extract_post(html: str) -> tuple[str, str]:
    """Return (canonical_url, clean_text) extracted from a Substack email HTML.

    Raises BodyTooShort if extracted text < MIN_BODY_CHARS so callers can skip cleanly.
    """
    if not html:
        raise BodyTooShort("empty html")

    soup = BeautifulSoup(html, "lxml")
    canonical_url = _find_canonical_url(soup, html)
    clean_text = _extract_body_text(html, soup)
    clean_text = _strip_chrome_lines(clean_text)

    if len(clean_text) < MIN_BODY_CHARS:
        raise BodyTooShort(f"only {len(clean_text)} chars after extraction")

    return canonical_url, clean_text


def _find_canonical_url(soup: BeautifulSoup, html: str) -> str:
    link = soup.find("link", attrs={"rel": "canonical"})
    if link and link.get("href"):
        return link["href"].strip()

    meta = soup.find("meta", attrs={"property": "og:url"})
    if meta and meta.get("content"):
        return meta["content"].strip()

    match = SUBSTACK_POST_RE.search(html)
    if match:
        return match.group(0)

    for domain_match in SUBSTACK_DOMAIN_RE.finditer(html):
        candidate = domain_match.group(0)
        if not _is_chrome_link(candidate):
            return candidate

    for anchor in soup.find_all("a", href=True):
        href = anchor["href"].strip()
        if "substack.com" in href.lower() and not _is_chrome_link(href):
            return href

    return ""


_CHROME_PATH_FRAGMENTS = ("/account", "/subscribe", "/profile", "/app", "/redirect")


def _is_chrome_link(href: str) -> bool:
    lower = href.lower()
    return any(frag in lower for frag in _CHROME_PATH_FRAGMENTS)


def _extract_body_text(html: str, soup: BeautifulSoup) -> str:
    try:
        doc = Document(html)
        summary_html = doc.summary(html_partial=True)
        text = BeautifulSoup(summary_html, "lxml").get_text(separator="\n", strip=True)
        if len(text) >= MIN_BODY_CHARS:
            return text
    except Exception as e:
        logger.debug("readability extraction failed: %s", e)

    article = soup.find("article")
    if article:
        text = article.get_text(separator="\n", strip=True)
        if text:
            return text

    divs = soup.find_all("div")
    if divs:
        biggest = max(divs, key=lambda d: len(d.get_text(strip=True)))
        return biggest.get_text(separator="\n", strip=True)

    return soup.get_text(separator="\n", strip=True)


def _strip_chrome_lines(text: str) -> str:
    kept = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if any(p.search(stripped) for p in CHROME_PATTERNS):
            continue
        kept.append(stripped)
    return "\n".join(kept)
