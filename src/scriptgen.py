import json
import logging
import re
import time

import anthropic

from src.config import (
    ANTHROPIC_API_KEY,
    CLAUDE_MODEL,
    PROMPTS_DIR,
    SCRIPTGEN_MAX_TOKENS,
    SCRIPTGEN_TEMPERATURE,
)

logger = logging.getLogger(__name__)

API_RETRY_DELAYS = [2, 8, 32]
RETRYABLE_STATUS_CODES = (429, 500, 503)

SCRIPT_PATTERN = re.compile(
    r"\[(INTERVIEWER|EXPERT)\]:\s*(.+?)(?=\[(?:INTERVIEWER|EXPERT)\]:|$)",
    re.DOTALL,
)


def build_script_prompt(themes: dict) -> str:
    """Load prompts/scriptgen.txt and inject the themes JSON."""
    return json.dumps(themes, indent=2, ensure_ascii=False)


def parse_script(raw_text: str) -> list[dict]:
    """Parse Claude's raw text output into structured segments.

    Expects lines starting with [INTERVIEWER]: or [EXPERT]:
    Returns list of ScriptSegment dicts.
    Raises ValueError if fewer than 4 segments parsed.
    """
    matches = SCRIPT_PATTERN.findall(raw_text)

    segments = [
        {"speaker": speaker.lower(), "text": text.strip()}
        for speaker, text in matches
    ]

    if len(segments) < 4:
        raise ValueError(
            f"Only {len(segments)} segments parsed (minimum 4 required). "
            f"Raw text starts with: {raw_text[:200]}"
        )

    return segments


def generate_script(themes: dict) -> list[dict]:
    """Call Claude API with the scriptgen prompt, then parse the result.

    On parse failure (ValueError from parse_script), retries once with
    a correction message. Retry: 3 attempts with exponential backoff on
    API errors. Hard fail (raise) if all retries exhausted.
    """
    system_prompt = (PROMPTS_DIR / "scriptgen.txt").read_text()
    user_message = build_script_prompt(themes)

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    messages = [{"role": "user", "content": user_message}]

    raw_text = _call_claude(client, system_prompt, messages)

    try:
        return parse_script(raw_text)
    except ValueError:
        pass

    # Retry once with correction
    logger.warning("Script parse failed — retrying with format correction")
    messages.append({"role": "assistant", "content": raw_text})
    messages.append({
        "role": "user",
        "content": "Please format your response using [INTERVIEWER]: and [EXPERT]: tags.",
    })

    raw_text = _call_claude(client, system_prompt, messages)

    # This time let the ValueError propagate if it still fails
    return parse_script(raw_text)


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
                max_tokens=SCRIPTGEN_MAX_TOKENS,
                temperature=SCRIPTGEN_TEMPERATURE,
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
