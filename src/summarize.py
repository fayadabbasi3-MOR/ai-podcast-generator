import json
import logging
import time
from typing import TypedDict

import anthropic

from src.config import (
    ANTHROPIC_API_KEY,
    CLAUDE_MODEL,
    PROMPTS_DIR,
    SUMMARIZE_MAX_TOKENS,
    SUMMARIZE_TEMPERATURE,
)
from src.sources import ContentItem


class NewsletterSummary(TypedDict):
    title: str
    publication: str
    author: str | None
    url: str
    one_liner: str
    summary: str
    key_takeaways: list[str]


class AggregateSummary(TypedDict):
    narrative: str
    cross_cutting_themes: list[str]
    notable_quotes: list[str]

logger = logging.getLogger(__name__)

API_RETRY_DELAYS = [2, 8, 32]  # exponential backoff seconds
RETRYABLE_STATUS_CODES = (429, 500, 503)


MAX_ITEMS_PER_PROVIDER = 150
MAX_PROMPT_CHARS = 400_000  # ~100K tokens, safely under 200K limit


def build_summarize_prompt(content: dict) -> str:
    """Load prompts/summarize.txt and inject the content dict as a formatted string.

    The user message includes all ContentItems grouped by provider,
    serialized as a readable list. Caps items per provider and total
    prompt length to stay within API token limits.
    """
    lines = []
    for provider in ("anthropic", "openai", "gemini"):
        items = content.get(provider, [])
        if not items:
            continue
        if len(items) > MAX_ITEMS_PER_PROVIDER:
            logger.warning(
                "Capping %s from %d to %d items in prompt",
                provider, len(items), MAX_ITEMS_PER_PROVIDER,
            )
            items = items[:MAX_ITEMS_PER_PROVIDER]
        lines.append(f"## {provider.upper()} ({len(items)} items)")
        for item in items:
            lines.append(f"- **{item.get('title', 'Untitled')}**")
            lines.append(f"  URL: {item.get('url', '')}")
            lines.append(f"  Published: {item.get('published', '')}")
            lines.append(f"  Summary: {item.get('summary', '')}")
        lines.append("")

    if content.get("errors"):
        lines.append(f"## ERRORS ({len(content['errors'])} sources failed)")
        for err in content["errors"]:
            lines.append(f"- {err['source']}: {err['error']}")

    result = "\n".join(lines)
    if len(result) > MAX_PROMPT_CHARS:
        logger.warning(
            "Prompt too long (%d chars), truncating to %d",
            len(result), MAX_PROMPT_CHARS,
        )
        result = result[:MAX_PROMPT_CHARS] + "\n\n[TRUNCATED — content exceeded limit]"
    return result


def summarize(content: dict) -> dict:
    """Call Claude API with the summarize prompt.

    Parses the response as JSON. Validates that "themes" key exists
    and contains at least one theme. On validation failure, retries
    once with a correction message appended.

    Retry: 3 attempts with exponential backoff (2s, 8s, 32s) on API errors.
    Hard fail (raise) if all retries exhausted.
    """
    system_prompt = (PROMPTS_DIR / "summarize.txt").read_text()
    user_message = build_summarize_prompt(content)

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    messages = [{"role": "user", "content": user_message}]

    raw_text = _call_claude(client, system_prompt, messages)

    # Try to parse as JSON
    result = _try_parse_json(raw_text)
    if result is not None and _validate_summarize_output(result):
        return result

    # Retry once with correction
    logger.warning("Invalid JSON from summarize — retrying with correction")
    messages.append({"role": "assistant", "content": raw_text})
    messages.append({
        "role": "user",
        "content": "Please format your response as valid JSON.",
    })

    raw_text = _call_claude(client, system_prompt, messages)
    result = _try_parse_json(raw_text)
    if result is not None and _validate_summarize_output(result):
        return result

    raise ValueError(f"Summarize failed to produce valid JSON after retry. Last response: {raw_text[:200]}")


def _call_claude(
    client: anthropic.Anthropic,
    system_prompt: str,
    messages: list[dict],
) -> str:
    """Call Claude API with retries on transient HTTP errors."""
    for attempt, delay in enumerate(API_RETRY_DELAYS):
        try:
            response = client.messages.create(
                model=CLAUDE_MODEL,
                max_tokens=SUMMARIZE_MAX_TOKENS,
                temperature=SUMMARIZE_TEMPERATURE,
                system=system_prompt,
                messages=messages,
            )
            if response.stop_reason == "max_tokens":
                logger.warning(
                    "Claude response truncated at %d tokens — increase SUMMARIZE_MAX_TOKENS",
                    SUMMARIZE_MAX_TOKENS,
                )
            return response.content[0].text
        except anthropic.APIStatusError as e:
            if e.status_code in RETRYABLE_STATUS_CODES and attempt < len(API_RETRY_DELAYS) - 1:
                logger.warning(
                    "Claude API error %d (attempt %d/%d), retrying in %ds",
                    e.status_code, attempt + 1, len(API_RETRY_DELAYS), delay,
                )
                time.sleep(delay)
            else:
                raise

    raise RuntimeError("All Claude API retries exhausted")


def _try_parse_json(text: str) -> dict | None:
    """Attempt to parse text as JSON, stripping markdown fences if present."""
    text = text.strip()

    # 1. Try raw parse first
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # 2. Extract content between ```json ... ``` fences
    import re
    fence_match = re.search(r"```(?:json)?\s*\n(.*?)```", text, re.DOTALL)
    if fence_match:
        try:
            return json.loads(fence_match.group(1).strip())
        except json.JSONDecodeError:
            pass

    # 3. Find the outermost { ... } and try parsing that
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end > start:
        try:
            return json.loads(text[start:end + 1])
        except json.JSONDecodeError:
            pass

    return None


def _validate_summarize_output(data: dict) -> bool:
    """Check that the response has 'themes' with at least one entry."""
    if not isinstance(data, dict):
        return False
    themes = data.get("themes")
    if not isinstance(themes, list) or len(themes) == 0:
        return False
    return True


# ── Substack: per-newsletter summary ──────────────────────────────────


def summarize_one(item: ContentItem, prompt_file: str = "summarize_substack.txt") -> NewsletterSummary:
    """Per-newsletter summary for the Substack pipeline.

    item: ContentItem with body_text populated.
    Returns a NewsletterSummary dict. Retry-once on bad JSON; raises on
    persistent failure.
    """
    item_label = item.get("url") or item.get("title") or item.get("id") or "<unknown>"

    system_prompt = (PROMPTS_DIR / prompt_file).read_text()
    user_message = json.dumps({
        "title": item.get("title", ""),
        "publication": item.get("source_meta", {}).get("publication", ""),
        "author": item.get("author"),
        "url": item.get("url", ""),
        "body_text": item.get("body_text", ""),
    }, ensure_ascii=False)

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    messages = [{"role": "user", "content": user_message}]

    raw = _call_claude(client, system_prompt, messages)
    parsed = _try_parse_json(raw)
    if parsed and _validate_newsletter_summary(parsed):
        return parsed

    logger.warning("Invalid summarize_one output for %s — retrying", item_label)
    messages.append({"role": "assistant", "content": raw})
    messages.append({"role": "user", "content": "Return ONLY valid JSON matching the specified shape."})
    raw = _call_claude(client, system_prompt, messages)
    parsed = _try_parse_json(raw)
    if parsed and _validate_newsletter_summary(parsed):
        return parsed

    raise ValueError(f"summarize_one failed for {item_label}: last response: {raw[:300]}")


def _validate_newsletter_summary(data: dict) -> bool:
    reason = _newsletter_summary_rejection(data)
    if reason:
        logger.warning("Newsletter summary rejected: %s", reason)
        return False
    return True


def _newsletter_summary_rejection(data: dict) -> str | None:
    """Return the rejection reason as a string, or None if valid."""
    if not isinstance(data, dict):
        return f"not a dict: {type(data).__name__}"
    required = {"title", "publication", "url", "one_liner", "summary", "key_takeaways"}
    missing = required - set(data.keys())
    if missing:
        return f"missing keys: {sorted(missing)}"
    if not isinstance(data["one_liner"], str):
        return f"one_liner not str: {type(data['one_liner']).__name__}"
    if len(data["one_liner"]) > 140:
        return f"one_liner length {len(data['one_liner'])} > 140"
    if not isinstance(data["key_takeaways"], list):
        return f"key_takeaways not list: {type(data['key_takeaways']).__name__}"
    return None


# ── Substack: aggregate summary ───────────────────────────────────────


def aggregate_summarize(
    per_item: list[NewsletterSummary],
    prompt_file: str = "aggregate_substack.txt",
    week_ending: str | None = None,
) -> AggregateSummary:
    """Cross-cutting wrap-up across the week's newsletter summaries."""
    system_prompt = (PROMPTS_DIR / prompt_file).read_text()
    user_message = json.dumps({
        "week_ending": week_ending or "",
        "newsletter_summaries": per_item,
    }, ensure_ascii=False)

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    messages = [{"role": "user", "content": user_message}]

    raw = _call_claude(client, system_prompt, messages)
    parsed = _try_parse_json(raw)
    if parsed and _validate_aggregate_summary(parsed):
        return parsed

    logger.warning("Invalid aggregate_summarize output — retrying")
    messages.append({"role": "assistant", "content": raw})
    messages.append({"role": "user", "content": "Return ONLY valid JSON matching the specified shape."})
    raw = _call_claude(client, system_prompt, messages)
    parsed = _try_parse_json(raw)
    if parsed and _validate_aggregate_summary(parsed):
        return parsed

    raise ValueError(f"aggregate_summarize failed: last response: {raw[:200]}")


def _validate_aggregate_summary(data: dict) -> bool:
    if not isinstance(data, dict):
        return False
    if not isinstance(data.get("narrative"), str) or len(data["narrative"]) < 100:
        return False
    if not isinstance(data.get("cross_cutting_themes"), list):
        return False
    if not isinstance(data.get("notable_quotes"), list):
        return False
    return True
