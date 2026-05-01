# Substack PM Weekly — Podcast Pipeline Spec

**Status:** Draft v1 (2026-05-01)
**Owner:** Fayad
**Repo target:** [`fayad-abbasi/ai-podcast-generator`](https://github.com/fayad-abbasi/ai-podcast-generator)

A second weekly podcast in the same repo as **AI Industry Weekly**: ingests paid Substack PM newsletters from Gmail, produces a two-speaker dialogue episode, and emails Fayad a structured summary with three role-specific action items. Same run also adds an email companion to the existing AI Industry Weekly episode.

## How to read this spec set

Read in order. ~30 min total.

| File | Purpose | Read when |
|---|---|---|
| `00-brainstorming.md` | Design Q&A archive — why each decision landed where it did | You disagree with a locked decision and want the receipts |
| `01-design.md` | Locked architecture: data flow, modules, contracts | You're about to code |
| `02-plan.md` | Bite-sized tasks (2–5 min) per milestone, with verification | You're executing |
| `03-prompts.md` | Verbatim LLM prompt templates with `{{placeholder}}` syntax | You're wiring summarize/scriptgen/action_items |
| `04-config-and-secrets.md` | Secrets list, Gmail OAuth one-time setup, env vars | First-run setup |
| `05-open-questions.md` | What still blocks execution | Before kicking off M1 |

## Scope at a glance

- **NEW** workflow: `substack-pm-weekly.yml` — Friday 06:00 UTC, cron `0 6 * * 5`
- **NEW** source plugin: `src/sources/substack_pm.py` (Gmail API)
- **REFACTOR**: existing ingest into `src/sources/ai_industry.py` behind a `Source` protocol
- **NEW** modules: `src/action_items.py`, `src/email_publish.py`
- **NEW** prompts: `prompts/summarize_substack.txt`, `prompts/scriptgen_substack.txt`, `prompts/action_items.txt`
- **MODIFY**: `.github/workflows/generate-episode.yml` (rename → `ai-industry-weekly.yml`) to call email_publish after publish
- **DEPRECATE**: `.github/workflows/notify-episode.yml` (Gmail SMTP) — replaced by `email_publish` invoked from each weekly workflow

## Two podcasts, one repo

| | AI Industry Weekly (existing) | Substack PM Weekly (new) |
|---|---|---|
| Cron | `0 1 * * 4` (Wed 8 PM ET) | `0 6 * * 5` (Fri 2 AM ET) |
| Source | 18 RSS/scrape feeds | Gmail label `Substack/PM` |
| Length | 1,500–2,000 words | Floats with content (no cap) |
| Structure | Themed clusters, 4–6 themes | Per-newsletter segments + aggregate + 3 actions |
| Email | Per-story summaries + aggregate + link (no actions) | Per-newsletter + aggregate + 3 actions + link |

## Conventions

- All code paths in this spec are **exact** relative to the repo root: `src/sources/substack_pm.py`, not "the new substack file."
- Prompt templates use `{{double_brace}}` placeholders.
- Verification steps in `02-plan.md` are runnable commands or observable artifacts, not "make sure it works."

## Out of scope (do not build)

- Per-Substack publication theming or voice tuning
- Public RSS feed for the Substack podcast (private to Fayad; episode URL via email only)
- Web UI, dashboard, or analytics
- Auto-unsubscribe / Gmail filter management from code
