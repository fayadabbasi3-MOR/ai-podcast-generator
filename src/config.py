import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# ── Paths ──────────────────────────────────────────────
ROOT_DIR = Path(__file__).resolve().parent.parent
PROMPTS_DIR = ROOT_DIR / "prompts"
SITE_DIR = ROOT_DIR / "site"
EPISODES_DIR = SITE_DIR / "episodes"

# ── API Keys (from env) ───────────────────────────────
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
GOOGLE_APPLICATION_CREDENTIALS = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "")

# ── Source List ────────────────────────────────────────
# Each source dict: name, provider, url, method, enabled
# method: "rss" | "atom" | "scrape" | "sitemap" | "api"
SOURCES: list[dict] = [
    # --- Anthropic ---
    {
        "name": "anthropic_blog",
        "provider": "anthropic",
        "url": "https://raw.githubusercontent.com/taobojlen/anthropic-rss-feed/main/anthropic_news_rss.xml",
        "method": "rss",
        "enabled": True,
    },
    {
        "name": "anthropic_engineering",
        "provider": "anthropic",
        "url": "https://raw.githubusercontent.com/taobojlen/anthropic-rss-feed/main/anthropic_engineering_rss.xml",
        "method": "rss",
        "enabled": True,
    },
    {
        "name": "anthropic_release_notes",
        "provider": "anthropic",
        "url": "https://platform.claude.com/docs/en/release-notes/overview",
        "method": "scrape",
        "css_selector": "article",
        "enabled": True,
    },
    {
        "name": "claude_code_releases",
        "provider": "anthropic",
        "url": "https://github.com/anthropics/claude-code/releases.atom",
        "method": "atom",
        "enabled": True,
    },
    {
        "name": "anthropic_python_sdk",
        "provider": "anthropic",
        "url": "https://github.com/anthropics/anthropic-sdk-python/releases.atom",
        "method": "atom",
        "enabled": True,
    },
    {
        "name": "anthropic_models",
        "provider": "anthropic",
        "url": "https://api.anthropic.com/v1/models",
        "method": "api",
        "enabled": True,
    },
    {
        "name": "anthropic_sitemap",
        "provider": "anthropic",
        "url": "https://platform.claude.com/sitemap.xml",
        "method": "sitemap",
        "enabled": True,
    },
    # --- OpenAI ---
    {
        "name": "openai_blog",
        "provider": "openai",
        "url": "https://openai.com/blog/rss.xml",
        "method": "rss",
        "enabled": True,
    },
    {
        "name": "openai_changelog",
        "provider": "openai",
        "url": "https://developers.openai.com/changelog/rss.xml",
        "method": "rss",
        "enabled": True,
    },
    {
        "name": "openai_community",
        "provider": "openai",
        "url": "https://community.openai.com/c/announcements/6.rss",
        "method": "rss",
        "enabled": True,
    },
    {
        "name": "openai_release_sitemap",
        "provider": "openai",
        "url": "https://openai.com/sitemap.xml/release/",
        "method": "sitemap",
        "enabled": True,
    },
    {
        "name": "openai_python_sdk",
        "provider": "openai",
        "url": "https://github.com/openai/openai-python/releases.atom",
        "method": "atom",
        "enabled": True,
    },
    {
        "name": "openai_status",
        "provider": "openai",
        "url": "https://status.openai.com/feed.rss",
        "method": "rss",
        "enabled": True,
    },
    # --- Google Gemini ---
    {
        "name": "google_ai_blog",
        "provider": "gemini",
        "url": "https://blog.google/technology/ai/rss/",
        "method": "rss",
        "enabled": True,
    },
    {
        "name": "google_developers_blog",
        "provider": "gemini",
        "url": "https://developers.googleblog.com/feeds/posts/default",
        "method": "rss",
        "enabled": True,
    },
    {
        "name": "gemini_api_changelog",
        "provider": "gemini",
        "url": "https://ai.google.dev/gemini-api/docs/changelog",
        "method": "scrape",
        "css_selector": "article",
        "enabled": True,
    },
    {
        "name": "vertex_ai_release_notes",
        "provider": "gemini",
        "url": "https://docs.cloud.google.com/feeds/generative-ai-on-vertex-ai-release-notes.xml",
        "method": "atom",
        "enabled": True,
    },
    {
        "name": "gemini_sitemap",
        "provider": "gemini",
        "url": "https://ai.google.dev/sitemap.xml",
        "method": "sitemap",
        "enabled": True,
    },
]

# ── Claude API ─────────────────────────────────────────
CLAUDE_MODEL = "claude-sonnet-4-6"
SUMMARIZE_MAX_TOKENS = 4096
SUMMARIZE_TEMPERATURE = 0.3
SCRIPTGEN_MAX_TOKENS = 8192
SCRIPTGEN_TEMPERATURE = 0.7

# ── TTS ────────────────────────────────────────────────
INTERVIEWER_VOICE = {
    "language_code": "en-US",
    "name": "en-US-Journey-F",
    "ssml_gender": "FEMALE",
}
EXPERT_VOICE = {
    "language_code": "en-US",
    "name": "en-US-Journey-D",
    "ssml_gender": "MALE",
}
TTS_CHUNK_BYTE_LIMIT = 4800

# ── Audio ──────────────────────────────────────────────
PAUSE_BETWEEN_SPEAKERS_MS = 400
MP3_BITRATE = 128000

# ── Episode ────────────────────────────────────────────
EPISODE_TARGET_WORDS = (1500, 2000)
LOOKBACK_DAYS = 7

# ── Publishing ─────────────────────────────────────────
PAGES_BASE_URL = os.environ.get("PAGES_BASE_URL", "")
PODCAST_TITLE = "AI Industry Weekly"
PODCAST_DESCRIPTION = "Weekly AI news from Anthropic, OpenAI, and Google — auto-generated podcast."
PODCAST_AUTHOR = ""
PODCAST_EMAIL = ""
PODCAST_LANGUAGE = "en-us"
PODCAST_CATEGORY = "Technology"
