# 00 — Brainstorming Archive

Captured Q&A from the design conversation. Read this when you want to understand **why** a decision landed, not what it is. The "what" lives in `01-design.md`.

---

## Q1. New repo or extend the existing one?

**Decision:** Extend `fayad-abbasi/ai-podcast-generator`. Same repo, two workflows, shared pipeline modules.

**Why:**
- Pipeline stages (summarize → scriptgen → tts → audio → publish) are 90% identical.
- Voice consistency: same TTS voices, same dialogue style, no fork drift.
- One place for credentials, one place for cron debugging.
- The only divergent stages are **ingest** and **summarize prompt**.

**Rejected alternatives:**
- New repo (`substack-podcast-pipeline`): doubles the maintenance surface, splits secrets.
- Branch in same repo: weekly main builds need to coexist; branches don't help.

---

## Q2. RSS or Gmail for Substack ingestion?

**Decision:** Gmail API with label filter `Substack/PM`, query last 7 days.

**Why:**
- Paid Substacks have **per-publication private RSS** with inconsistent rollout — some publications expose it, some don't, some require a paid-account session cookie that rotates.
- Gmail is **deterministic**: every paid subscription delivers via email. If Fayad subscribes, it lands. If he unsubscribes, it stops.
- Inclusion list is managed by **Gmail filter UI**, not by code. Adding a Substack = "add sender to filter that applies label `Substack/PM`." No PR, no merge, no deploy.
- Body extraction is solvable (BeautifulSoup / readability-lxml).

**Tradeoffs accepted:**
- Gmail OAuth setup is a one-time pain (covered in `04-config-and-secrets.md`).
- Body parsing is HTML-fragile; Substack template is uniform enough to handle generically.

**Rejected:**
- Polling Substack's authenticated RSS per publication: brittle, requires per-pub config.
- Email forwarding to a webhook: needs hosted ingestion endpoint; we want pure GH Actions.

---

## Q3. How is "this week's set" defined?

**Decision:** Gmail query `label:Substack/PM newer_than:7d`. Dedup by Gmail message ID. Snapshot processed IDs to `state/substack_seen.json`, committed back from the workflow.

**Why:**
- `newer_than:7d` aligns with the weekly cadence and tolerates a missed run (next run picks up overlap, dedupe drops it).
- Gmail message IDs are immutable — perfect dedup key.
- Snapshotting back to the repo (same pattern as existing `snapshots/` branch in `diff.py`) keeps state version-controlled, observable, and free.

---

## Q4. Length cap?

**Decision:** No hard cap. Episode floats with content.

**User quote (paraphrased):** "I don't want to abbreviate just because a week had a lot of content. If there are 12 newsletters, give me 60 minutes. If there are 3, give me 15."

**Implementation:** Per-newsletter target ~5 min of script (≈750 words). Scriptgen prompt sets per-segment target, not total cap. TTS handles arbitrary length via existing chunking.

**Cost note:** TTS cost scales linearly with audio length; Anthropic costs scale with input. Both are bounded by realistic newsletter volume (likely 5–10/week). Not worth a cap.

---

## Q5. Voice / format?

**Decision:** Two-speaker dialogue, same speakers as AI Industry Weekly: `[INTERVIEWER]` (en-US-Journey-F) and `[EXPERT]` (en-US-Journey-D).

**Why:** Voice parity across both podcasts. Fayad's ear is already tuned. No new voice procurement.

---

## Q6. Episode structure?

**Decision:**
1. **Intro** — week-of date, count of newsletters covered (~30s)
2. **Per-newsletter segments** — each ~5 min, [INTERVIEWER] sets up the publication + author, [EXPERT] explains the post, both react
3. **Aggregate summary** — cross-cutting themes across the week's newsletters (~2–3 min)
4. **Action items** — three role-specific items for Fayad, read aloud (~1 min)
5. **Outro** — sign-off (~15s)

**Why action items in the audio AND email:** Fayad listens on commute (audio), references on laptop (email). Same content, two delivery modes.

---

## Q7. Action item generation — what makes them "specific"?

**Decision:** A dedicated `src/action_items.py` module that injects sliced fields from `MEMORY.md` and `USER.md` into the prompt. The prompt sees:
- **Role:** DevEx PM at impact.com (Logan = manager, Radical Candor)
- **Current projects:** Port tooling, GitHub workflow setup, Cape Town summit prep, ShapeUp adoption
- **Eve system context:** assistant evolution phases, current operating mode
- **Brand goals:** 500 followers, 6–12 content pieces in 2026, DevEx thought leadership

The slice is **explicitly enumerated** in `03-prompts.md` (not "the whole MEMORY file") — this both keeps prompt size sane and makes it auditable.

**Each action item must:**
- Reference one specific newsletter from the week (by title + URL).
- Be doable in ≤30 minutes that week.
- Tie to a current project or brand goal, not generic PM advice.

---

## Q8. Email companion — same template for both podcasts?

**Decision:** Yes, same `src/email_publish.py` module, same Markdown→HTML template. AI Industry Weekly sets a config flag `include_action_items: false`. Substack PM sets `true`.

**Email contents:**
- Subject: `[Podcast] {{podcast_name}} — {{week_ending}}`
- Body: per-item summaries, aggregate summary, conditional action items, link to MP3
- Sender: TBD (see `05-open-questions.md`, Q-1)
- Recipient: `fayadabbasi3@gmail.com`

---

## Q9. Resend vs existing Gmail SMTP?

**Discovery during spec:** The existing repo's `notify-episode.yml` uses **Gmail SMTP** (`GMAIL_SENDER` + `GMAIL_APP_PASSWORD`), NOT Resend. Fayad's recollection that Resend was already wired in is incorrect.

**Decision (default):** Adopt **Resend** as the email transport for `email_publish.py`, per the locked design. Gmail SMTP is acceptable as a fallback if Fayad doesn't want to add a new vendor — but Resend gives us:
- Better deliverability + analytics
- HTML rendering without app-password fragility
- Verified-domain sending (looks pro, not like spam from your own Gmail)

This is flagged in `05-open-questions.md` as Q-1 because it changes the secrets list. Default in this spec is **Resend**.

---

## Q10. Does the existing pipeline already have a `--source` flag?

**Discovery:** No. `src/pipeline.py` only takes `--dry-run` today. The ingestion sources are statically loaded from `src/config.py` (`SOURCES` list).

**Implication:** M2 must add `--source {ai_industry,substack_pm}` and route to a source plugin module. The existing 18-feed config moves into `src/sources/ai_industry.py`.

---

## Q11. Does the existing summarize pipeline cluster by AI provider?

**Discovery:** Yes. The current `summarize.py` prompt expects items grouped by `anthropic | openai | gemini`, and clusters into themes across providers.

**Implication:** This prompt is **not reusable** for Substack — Substack newsletters don't fit a "provider" axis. We need a separate prompt `prompts/summarize_substack.txt` that produces per-newsletter summaries (no clustering across newsletters). Aggregate-summary stage is a second LLM call on top.

---

## Q12. Where does the snapshot/dedup state live?

**Decision:** `state/substack_seen.json` on the main branch, committed from the workflow at the end of a successful run.

**Schema:**
```json
{
  "last_run_utc": "2026-05-08T06:00:00Z",
  "seen_message_ids": ["<gmail-msg-id-1>", "<gmail-msg-id-2>", ...],
  "retention_days": 30
}
```

Old IDs aged out after 30 days (Gmail `newer_than:7d` already excludes them; retention bound prevents file bloat over years).

**Why not a separate `snapshots` branch like ingest.py uses?** That branch is for content snapshots (HTML hashes, sitemap URLs) that get noisy. Message IDs are cheap and live happily on main.

---

## Q13. Failure modes — what if Gmail returns 0 messages?

**Decision:** Skip the run cleanly. Send a short "no newsletters this week" email; do not generate an empty episode.

**Why:** Cheaper than producing a 30-second filler episode. Email is the persistent artifact; missing audio is fine.

---

## Q14. Failure modes — what if a newsletter body fails to parse?

**Decision:** Log it, skip that newsletter, continue with the rest. Surface the count of skipped newsletters in the email aggregate.

**Why:** One bad parse shouldn't kill the whole episode. We'd rather ship 5/6 than 0/6.

---

## Q15. Observability?

**Decision (minimal):**
- Workflow status badge in repo README (both workflows)
- On failure, post to Slack `#inbox` via webhook (existing pattern from Fayad's stack)
- No dashboards, no metrics emission. If Fayad doesn't get an email Friday morning, that's the alert.

---

## Q16. Why Friday 6 AM UTC and not, say, Monday?

**Decision:** Friday 06:00 UTC = Friday 02:00 ET. Episode lands in Fayad's inbox before he wakes up Friday → he has it for the commute / weekend reading.

Substack publication cadence is mostly Mon–Thu; Friday lookback covers the full editorial week. Monday lookback would split the week awkwardly across the weekend.

---

## Q17. What about `MEMORY.md` updating mid-week?

**Decision:** Action items prompt reads MEMORY.md and USER.md **at workflow runtime** (Friday morning), so it always sees the freshest state. No caching.

The repo doesn't have access to `/home/fayadabbasi/Documents/MEMORY.md` — that's local. The action_items module needs the relevant slices either:
- Committed into the repo at `prompts/context/role.md` and `prompts/context/projects.md` (Fayad updates these manually as projects evolve), OR
- Pulled from a private gist / private repo at runtime.

**Default for this spec:** Option A (committed slices). See `05-open-questions.md` Q-2.

---

## Q18. Anything we explicitly decided NOT to do?

- ❌ Auto-classify newsletters by topic for grouping. Each newsletter is its own segment; no cross-newsletter clustering.
- ❌ Per-newsletter voice / persona variation.
- ❌ Auto-tune the action items based on past episodes. Each week is independent.
- ❌ Push the Substack podcast to a public RSS feed. Private to Fayad.
- ❌ Run on missed-week catchup logic. If a Friday is missed, the next Friday picks up the last 7 days only.
