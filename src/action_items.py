import json
import logging
import time
from pathlib import Path
from typing import TypedDict

import anthropic

from src.config import (
    ACTION_ITEMS_COUNT,
    ANTHROPIC_API_KEY,
    CLAUDE_MODEL,
    PROMPTS_DIR,
    ROOT_DIR,
    SUMMARIZE_MAX_TOKENS,
    SUMMARIZE_TEMPERATURE,
)
from src.summarize import AggregateSummary, NewsletterSummary, _try_parse_json

logger = logging.getLogger(__name__)

API_RETRY_DELAYS = [2, 8, 32]
RETRYABLE_STATUS_CODES = (429, 500, 503)

CONTEXT_DIR = ROOT_DIR / "prompts" / "context"
ROLE_FILE = CONTEXT_DIR / "role.md"
PROJECTS_FILE = CONTEXT_DIR / "projects.md"


class ActionItem(TypedDict):
    title: str
    description: str
    source_url: str
    estimated_minutes: int


def load_memory_slices(
    role_path: Path | None = None,
    projects_path: Path | None = None,
) -> dict[str, str]:
    """Read role.md and projects.md verbatim. Empty file is treated as empty string;
    missing file raises so the model never receives a silent empty context."""
    role = (role_path or ROLE_FILE).read_text()
    projects = (projects_path or PROJECTS_FILE).read_text()
    return {"role": role, "projects": projects}


def generate_action_items(
    per_item: list[NewsletterSummary],
    aggregate: AggregateSummary,
    memory_slices: dict[str, str],
    week_ending: str | None = None,
    prompt_file: str = "action_items.txt",
) -> list[ActionItem]:
    """Generate exactly ACTION_ITEMS_COUNT action items grounded in Fayad's
    role + projects. Validates each item's source_url is present in the
    input newsletter set. Retry-once on validation failure with stricter
    system prompt prefix."""
    template = (PROMPTS_DIR / prompt_file).read_text()
    system_prompt = template.replace(
        "{{role_slice}}", memory_slices.get("role", "")
    ).replace(
        "{{projects_slice}}", memory_slices.get("projects", "")
    )

    user_message = json.dumps({
        "week_ending": week_ending or "",
        "newsletter_summaries": per_item,
        "aggregate": aggregate,
    }, ensure_ascii=False)

    valid_urls = {s.get("url", "") for s in per_item if s.get("url")}

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    messages = [{"role": "user", "content": user_message}]

    raw = _call_claude(client, system_prompt, messages)
    items = _parse_and_validate(raw, valid_urls)
    if items is not None:
        return items

    logger.warning("action_items validation failed — retrying with stricter prefix")
    stricter_system = (
        "RETURN ONLY VALID JSON. EXACTLY 3 ITEMS. EACH source_url MUST APPEAR "
        "IN THE PROVIDED NEWSLETTERS. estimated_minutes BETWEEN 10 AND 30.\n\n"
    ) + system_prompt
    messages.append({"role": "assistant", "content": raw})
    messages.append({"role": "user", "content": "Your previous response failed validation. Try again."})
    raw = _call_claude(client, stricter_system, messages)
    items = _parse_and_validate(raw, valid_urls)
    if items is not None:
        return items

    raise ValueError(f"action_items failed validation after retry: {raw[:200]}")


def _parse_and_validate(raw: str, valid_urls: set[str]) -> list[ActionItem] | None:
    parsed = _try_parse_json(raw)
    if not parsed or not isinstance(parsed, dict):
        return None
    items = parsed.get("items")
    if not isinstance(items, list) or len(items) != ACTION_ITEMS_COUNT:
        return None
    for item in items:
        if not isinstance(item, dict):
            return None
        for key in ("title", "description", "source_url", "estimated_minutes"):
            if key not in item:
                return None
        if not isinstance(item["title"], str) or not item["title"].strip():
            return None
        if not isinstance(item["description"], str) or not item["description"].strip():
            return None
        if not isinstance(item["source_url"], str) or item["source_url"] not in valid_urls:
            return None
        mins = item.get("estimated_minutes")
        if not isinstance(mins, int) or not (10 <= mins <= 30):
            return None
    return items


def _call_claude(
    client: anthropic.Anthropic,
    system_prompt: str,
    messages: list[dict],
) -> str:
    for attempt, delay in enumerate(API_RETRY_DELAYS):
        try:
            response = client.messages.create(
                model=CLAUDE_MODEL,
                max_tokens=SUMMARIZE_MAX_TOKENS,
                temperature=SUMMARIZE_TEMPERATURE,
                system=system_prompt,
                messages=messages,
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
