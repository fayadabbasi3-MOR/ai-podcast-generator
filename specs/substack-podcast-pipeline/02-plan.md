# 02 — Implementation Plan

Tasks are 2–5 min each. Each has an exact path and a verification step. Tasks within a milestone may be parallelizable; milestones are sequential.

**Conventions:**
- ✅ = verification passes
- File paths are relative to repo root
- "Verify" steps are runnable commands or observable artifacts

---

## M1 — Setup (≈25 min total)

### M1.1 — Branch off
- **Path:** repo root
- **Do:** `git checkout -b feat/substack-pm-podcast`
- **Verify:** ✅ `git status` shows new branch

### M1.2 — Create source plugin directory
- **Path:** `src/sources/`
- **Do:** `mkdir src/sources && touch src/sources/__init__.py`
- **Verify:** ✅ `ls src/sources/__init__.py` exists

### M1.3 — Create state directory
- **Path:** `state/`
- **Do:** `mkdir state && echo '{"last_run_utc": null, "seen_message_ids": [], "retention_days": 30}' > state/substack_seen.json`
- **Verify:** ✅ `python -c "import json; json.load(open('state/substack_seen.json'))"` exits 0

### M1.4 — Create context directory for memory slices
- **Path:** `prompts/context/`
- **Do:** `mkdir prompts/context` and create `role.md` + `projects.md` with content from `04-config-and-secrets.md` §"Memory slice contents"
- **Verify:** ✅ Both files exist with non-empty content; ✅ no PII outside what Fayad explicitly committed

### M1.5 — Add deps to `requirements.txt`
- **Path:** `requirements.txt`
- **Do:** Append:
  ```
  google-api-python-client>=2.120.0
  google-auth>=2.28.0
  google-auth-oauthlib>=1.2.0
  readability-lxml>=0.8.1
  resend>=0.8.0
  markdown>=3.5.0
  ```
- **Verify:** ✅ `pip install -r requirements.txt` clean install in fresh venv

### M1.6 — Add Substack constants to `src/config.py`
- **Path:** `src/config.py`
- **Do:** Append:
  ```python
  SUBSTACK_GMAIL_LABEL = "Substack/PM"
  SUBSTACK_LOOKBACK_DAYS = 7
  SUBSTACK_PER_SEGMENT_TARGET_WORDS = 750
  SUBSTACK_FEED_DIR = "site/substack"
  SUBSTACK_PODCAST_TITLE = "Substack PM Weekly"
  STATE_DIR = "state"
  SUBSTACK_SEEN_FILE = "state/substack_seen.json"
  ACTION_ITEMS_COUNT = 3
  ```
- **Verify:** ✅ `python -c "from src import config; print(config.SUBSTACK_GMAIL_LABEL)"` prints `Substack/PM`

### M1.7 — Document GH secrets to add (no code)
- **Path:** `04-config-and-secrets.md` (already in spec)
- **Do:** Confirm Fayad will add: `GMAIL_OAUTH_CLIENT_ID`, `GMAIL_OAUTH_CLIENT_SECRET`, `GMAIL_OAUTH_REFRESH_TOKEN`, `RESEND_API_KEY`, `RECIPIENT_EMAIL`, `SLACK_WEBHOOK_INBOX`
- **Verify:** ✅ Fayad confirms all 6 secrets added in repo Settings → Secrets

---

## M2 — Ingestion refactor (≈55 min total)

### M2.1 — Define `Source` protocol
- **Path:** `src/sources/__init__.py`
- **Do:** Add `ContentItem` TypedDict + `Source` Protocol per `01-design.md` §"Source protocol"
- **Verify:** ✅ `python -c "from src.sources import Source, ContentItem"` imports without error

### M2.2 — Extract AI Industry source
- **Path:** `src/sources/ai_industry.py`
- **Do:** Copy `ingest_all()` from `src/ingest.py`. Wrap into `class AIIndustrySource: name = "ai_industry"; def fetch(self, since_days)`. Map result to `list[ContentItem]` (id = sha256(url), body_text = summary, source_meta = {provider, method}).
- **Verify:** ✅ Unit test `tests/test_ai_industry_source.py`: mock RSS, assert `fetch()` returns ≥1 ContentItem with all required fields

### M2.3 — Convert `src/ingest.py` to shim
- **Path:** `src/ingest.py`
- **Do:** Keep `ingest_all` function but reimplement as:
  ```python
  def ingest_all(sources, since_days=7):
      """Deprecated; routes to AIIndustrySource for backwards compat."""
      from src.sources.ai_industry import AIIndustrySource
      return AIIndustrySource()._fetch_legacy(sources, since_days)
  ```
- **Verify:** ✅ Existing `pytest tests/` still passes (no behavior change for AI Industry path)

### M2.4 — Implement Gmail client wrapper
- **Path:** `src/sources/_gmail_client.py` (new helper, prefixed `_` to mark internal)
- **Do:** Build a thin wrapper that:
  - Loads OAuth refresh token from env (`GMAIL_OAUTH_*`)
  - Calls `messages.list(q=...)` with pagination
  - Calls `messages.get(format='full')` for each id
  - Returns list of dicts: `{id, internal_date, headers, html_body, plain_body}`
- **Verify:** ✅ Unit test with `responses` mock returns expected payload shape

### M2.5 — Implement body extraction helper
- **Path:** `src/sources/_substack_body.py`
- **Do:** Function `extract_post(html: str) -> tuple[str, str]` returning `(canonical_url, clean_text)`. Implementation per `01-design.md` §"Body extraction strategy".
- **Verify:** ✅ Unit test `tests/test_substack_body.py`: feed a saved sample Substack email HTML, assert `len(clean_text) > 500` and URL starts with `https://`

### M2.6 — Implement `SubstackPMSource`
- **Path:** `src/sources/substack_pm.py`
- **Do:**
  - `class SubstackPMSource: name = "substack_pm"`
  - `fetch()` method orchestrates: gmail client → dedup against `state/substack_seen.json` → body extract → ContentItem list
  - Tracks pending-to-add IDs on `self._pending_seen_ids` for caller to flush after success
  - Method `mark_processed(item_ids: list[str])` writes `state/substack_seen.json` (called by pipeline after publish succeeds)
- **Verify:** ✅ Unit test mocking Gmail + body extract: assert dedup filters known IDs, assert mark_processed updates state file

### M2.7 — Add `--source` flag to `pipeline.py`
- **Path:** `src/pipeline.py`
- **Do:** Add argparse choice `--source {ai_industry,substack_pm}`, required. Branch logic per `01-design.md` §"`src/pipeline.py` — modified".
- **Verify:** ✅ `python -m src.pipeline --source ai_industry --dry-run` runs through ingest + summarize + scriptgen and prints script (existing dry-run behavior preserved); ✅ `python -m src.pipeline --source substack_pm --dry-run` (with Gmail creds in `.env`) runs through to script print

---

## M3 — Pipeline updates (≈60 min total)

### M3.1 — Write `prompts/summarize_substack.txt`
- **Path:** `prompts/summarize_substack.txt`
- **Do:** Per-newsletter summary prompt. Verbatim text in `03-prompts.md` §3.1.
- **Verify:** ✅ File exists, content matches spec

### M3.2 — Add `summarize_one()` in `summarize.py`
- **Path:** `src/summarize.py`
- **Do:** New function `summarize_one(item: ContentItem, prompt_file: str) -> NewsletterSummary`. Calls Claude with system prompt loaded from `prompts/{prompt_file}` and user message = JSON of the item. Validates output JSON shape.
- **Verify:** ✅ Unit test `tests/test_summarize_one.py` with mocked Anthropic returns valid `NewsletterSummary`

### M3.3 — Write `prompts/aggregate_substack.txt`
- **Path:** `prompts/aggregate_substack.txt`
- **Do:** Aggregate-summary prompt. Verbatim text in `03-prompts.md` §3.2.
- **Verify:** ✅ File exists

### M3.4 — Add `aggregate_summarize()` in `summarize.py`
- **Path:** `src/summarize.py`
- **Do:** New function `aggregate_summarize(per_item: list[NewsletterSummary], prompt_file: str) -> AggregateSummary`. AggregateSummary TypedDict: `{narrative: str, cross_cutting_themes: list[str], notable_quotes: list[str]}`.
- **Verify:** ✅ Unit test mocked: returns valid AggregateSummary

### M3.5 — Write `prompts/action_items.txt`
- **Path:** `prompts/action_items.txt`
- **Do:** Action items prompt with `{{role}}`, `{{projects}}`, `{{newsletters_json}}`, `{{aggregate_summary}}` placeholders. Verbatim in `03-prompts.md` §3.3.
- **Verify:** ✅ File exists

### M3.6 — Implement `src/action_items.py`
- **Path:** `src/action_items.py`
- **Do:**
  - `load_memory_slices() -> dict` reads `prompts/context/role.md` + `prompts/context/projects.md`
  - `generate_action_items(per_item, aggregate, memory_slices) -> list[ActionItem]`
  - Validates exactly 3 items, all required fields present, `estimated_minutes <= 30`
  - Retry-once on validation failure with stricter system prompt prefix
- **Verify:** ✅ Unit test: mocked Anthropic returns 3 valid items, `estimated_minutes` all ≤30, each has `source_url` matching one of the input newsletters

### M3.7 — Write `prompts/scriptgen_substack.txt`
- **Path:** `prompts/scriptgen_substack.txt`
- **Do:** Two-speaker dialogue prompt for Substack episode structure. Verbatim in `03-prompts.md` §3.4.
- **Verify:** ✅ File exists

### M3.8 — Add `generate_substack_script()` in `scriptgen.py`
- **Path:** `src/scriptgen.py`
- **Do:** New function per `01-design.md` §"`src/scriptgen.py` — modified". Loads `prompts/scriptgen_substack.txt`, sends user message with structured JSON of inputs, returns dialogue.
- **Verify:** ✅ Unit test mocked: returns string with both `[INTERVIEWER]:` and `[EXPERT]:` lines, INTERVIEWER speaks first

### M3.9 — Wire substack path in `pipeline.py`
- **Path:** `src/pipeline.py`
- **Do:** Implement the 10-step flow per `01-design.md` §"Pipeline stage order (substack_pm path)". Includes the 0-newsletters short-circuit and `mark_processed()` call after publish succeeds.
- **Verify:** ✅ End-to-end dry run with mocked Gmail returning 2 sample items prints valid script + would-send email payload

### M3.10 — Update `src/publish.py` for separate Substack feed
- **Path:** `src/publish.py`
- **Do:** Add `feed_path` and `episodes_dir` parameters to existing functions, default to current AI Industry locations. Substack path passes `site/substack/feed.xml` and `site/substack/episodes/`.
- **Verify:** ✅ Both feeds exist after a substack run; ✅ AI Industry feed unchanged

---

## M4 — Email companion (≈30 min total)

### M4.1 — Implement `src/email_publish.py` (transport + render)
- **Path:** `src/email_publish.py`
- **Do:**
  - `_render_markdown(podcast_name, week_ending, per_item, aggregate, action_items, episode_url) -> tuple[str, str]` returns `(markdown, html)`
  - `send_episode_email(...)` posts to Resend API with both `text` and `html` fields
  - Retry-once on 4xx/5xx with 30s backoff
- **Verify:** ✅ Unit test with mocked Resend client: assert payload has `to`, `subject`, `html`, `text`; assert action items block omitted when `action_items=None`

### M4.2 — Markdown template
- **Path:** `src/email_publish.py` (inline f-string template)
- **Do:** Implement template per `01-design.md` §"Email contract"
- **Verify:** ✅ Snapshot test: render with sample inputs, compare HTML against committed `tests/fixtures/expected_email.html`

### M4.3 — Wire email send into pipeline
- **Path:** `src/pipeline.py`
- **Do:** After `publish.update_feed()` succeeds, call `email_publish.send_episode_email()` with `include_action_items` derived from `--source` flag
- **Verify:** ✅ Dry run prints "Would send email to {RECIPIENT_EMAIL}" with body preview

### M4.4 — Add "no newsletters" email path
- **Path:** `src/email_publish.py`
- **Do:** Function `send_empty_week_email(podcast_name, recipient)` — minimal one-line email
- **Verify:** ✅ Unit test confirms send is called with subject `[Podcast] Substack PM Weekly — no newsletters this week`

---

## M5 — Cron + observability (≈25 min total)

### M5.1 — Rename existing workflow
- **Path:** `.github/workflows/generate-episode.yml` → `.github/workflows/ai-industry-weekly.yml`
- **Do:** `git mv` and update `workflow_run` reference in `notify-episode.yml` (which we'll delete in M5.4)
- **Verify:** ✅ GitHub Actions tab shows renamed workflow on next push

### M5.2 — Add email step to `ai-industry-weekly.yml`
- **Path:** `.github/workflows/ai-industry-weekly.yml`
- **Do:** After "Run podcast pipeline" step, add a step that calls `python -m src.email_publish --podcast ai_industry --episode-url $EPISODE_URL`. Pipeline already calls email_publish from inside, so this step is a NO-OP — just remove the standalone call. Actually: keep email call inside pipeline.py only. This task collapses to: pass `RESEND_API_KEY` and `RECIPIENT_EMAIL` env to the existing pipeline step.
- **Verify:** ✅ Workflow YAML lints clean; ✅ a manual `workflow_dispatch` run sends a real email

### M5.3 — Create `.github/workflows/substack-pm-weekly.yml`
- **Path:** `.github/workflows/substack-pm-weekly.yml`
- **Do:** Copy structure from `ai-industry-weekly.yml`. Changes:
  - `name: Substack PM Weekly`
  - `on.schedule.cron: '0 6 * * 5'`
  - Add env vars: `GMAIL_OAUTH_CLIENT_ID`, `GMAIL_OAUTH_CLIENT_SECRET`, `GMAIL_OAUTH_REFRESH_TOKEN`, `RESEND_API_KEY`, `RECIPIENT_EMAIL`
  - Pipeline step: `python -m src.pipeline --source substack_pm`
  - Add commit step for `state/substack_seen.json` (in addition to existing site/ commit)
- **Verify:** ✅ Workflow YAML lints clean (`actionlint .github/workflows/substack-pm-weekly.yml`); ✅ manual `workflow_dispatch` run produces episode + email; ✅ `state/substack_seen.json` updated with new IDs after run

### M5.4 — Delete obsolete `notify-episode.yml`
- **Path:** `.github/workflows/notify-episode.yml`
- **Do:** `git rm .github/workflows/notify-episode.yml`. (Email is now in-pipeline via Resend; the SMTP notify workflow is dead code.)
- **Verify:** ✅ File removed; ✅ AI Industry weekly run still produces an email (via the new path)

### M5.5 — Add status badges to README
- **Path:** `README.md` (repo root)
- **Do:** Append two badges:
  ```
  ![AI Industry Weekly](https://github.com/fayad-abbasi/ai-podcast-generator/actions/workflows/ai-industry-weekly.yml/badge.svg)
  ![Substack PM Weekly](https://github.com/fayad-abbasi/ai-podcast-generator/actions/workflows/substack-pm-weekly.yml/badge.svg)
  ```
- **Verify:** ✅ Badges render on GitHub repo page

### M5.6 — Add Slack failure alert step
- **Path:** both workflow YAMLs
- **Do:** Append final step `if: failure()` that POSTs to `${{ secrets.SLACK_WEBHOOK_INBOX }}` with payload `{"text": "Workflow {{ github.workflow }} failed: {{ github.server_url }}/{{ github.repository }}/actions/runs/{{ github.run_id }}"}`
- **Verify:** ✅ Force-fail a manual run (insert `exit 1` in pipeline temporarily) and confirm Slack #inbox receives a message; ✅ revert the forced fail

### M5.7 — End-to-end smoke test
- **Path:** repo via `workflow_dispatch`
- **Do:** Manually trigger `substack-pm-weekly.yml` on a Tuesday (off-cycle) to verify:
  1. Gmail fetch returns >0 newsletters
  2. Episode MP3 lands at `site/substack/episodes/episode_*.mp3`
  3. Email arrives at `fayadabbasi3@gmail.com` within 5 min
  4. `state/substack_seen.json` shows new IDs after the run
- **Verify:** ✅ All four observed; ✅ subsequent dispatch run within the same week sends "no newsletters this week" email (dedup working)

### M5.8 — Update `MEMORY.md` cron status
- **Path:** Fayad updates `/home/fayadabbasi/Documents/MEMORY.md` (NOT touched by Claude in this task)
- **Do (Fayad):** Mark Substack pipeline status from 🔴 DEAD → 🟢 LIVE only after **two consecutive Friday runs land**, per the "Verify Persistence Before Marking Complete" memory.
- **Verify:** ✅ Two confirmed Fridays of email delivery before status flip

---

## Done definition

- [ ] Both workflows green on GitHub Actions
- [ ] Two consecutive Friday Substack episodes delivered to inbox
- [ ] Two consecutive Wednesday AI Industry episodes deliver email companion
- [ ] `state/substack_seen.json` growing across runs (proof of dedup)
- [ ] Slack alert fires on a deliberate failure injection
