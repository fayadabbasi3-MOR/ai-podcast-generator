# 05 — Open Questions

Only items that genuinely block execution. Sensible defaults stated where possible.

---

## Q-1. Resend vs. existing Gmail SMTP — confirm direction

**Discovery:** The existing repo's `notify-episode.yml` uses **Gmail SMTP** (`GMAIL_SENDER` + `GMAIL_APP_PASSWORD`), not Resend. Fayad's recollection that Resend was already wired in is incorrect.

**Default in this spec:** Adopt Resend (per locked design). Adds `RESEND_API_KEY` secret + a verified sending domain.

**Decision needed from Fayad:**
- (A) Stick with Resend → need to verify a domain (e.g. `podcasts.fayadabbasi.com` or use Resend's onboarding sandbox `onboarding@resend.dev` for dev only). ~15 min DNS setup.
- (B) Reuse Gmail SMTP → reuse existing secrets, drop Resend dep, port `notify-episode.yml`'s send logic into `email_publish.py`. Simpler. Less polished HTML deliverability.

**Recommendation:** (A) Resend, because the email is the load-bearing artifact ("the email IS the heartbeat") and Gmail-SMTP-with-app-password is on Google's deprecation radar.

**Blocks:** M4.1, M4.2, M5.4

---

## Q-2. Memory slice source — committed file vs. private gist

**Default in this spec:** Committed Markdown files at `prompts/context/role.md` and `prompts/context/projects.md`. Fayad maintains them.

**Alternative:** Pull from a private gist or private repo at runtime (so Fayad can edit without a PR to the podcast repo).

**Tradeoff:** Committed files = simpler, version-controlled, auditable. Gist = lower-friction edits but adds an auth surface and a secret.

**Recommendation:** Default (committed files). A two-line MEMORY → role.md/projects.md sync can be a 5/1 task in Fayad's main system if friction becomes real.

**Blocks:** M3.6

---

## Q-3. Resend sender domain

If we go Resend (Q-1 = A): which domain?

**Options:**
- (A) `podcasts.fayadabbasi.com` — needs DNS access; nicest brand
- (B) `onboarding@resend.dev` — Resend's free shared domain; only sends to verified addresses (Fayad's own gmail counts); zero setup; can't scale to multiple recipients later
- (C) Skip the verified domain step; send via personal email address auth — Resend doesn't really support this

**Recommendation:** (B) for week-1 ship, (A) as a Friday-2 task if Fayad wants the brand polish.

**Blocks:** M4.1 only if Fayad wants a real domain on day 1; otherwise default to (B).

---

## Q-4. Substack podcast — public RSS or private only?

**Spec default:** Private. RSS at `site/substack/feed.xml` exists for podcast app subscription if Fayad wants it himself, but URL is not advertised anywhere.

**Decision needed only if:** Fayad wants to make this public (would need to think about: licensing of summarized newsletter content, attribution UX, whether publication owners care).

**Recommendation:** Stay private. Revisit only if Fayad wants to share it.

**Blocks:** Nothing — current spec ships private; flipping to public is a non-blocking future enhancement.

---

## Q-5. What if no `Substack/PM` Gmail label exists yet?

Fayad almost certainly has the label (mentioned in MEMORY: "Substack ingestion pipeline" as a known concept), but the spec assumes it exists.

**Action:** Before running the workflow the first time, Fayad confirms:
1. Gmail label `Substack/PM` exists
2. ≥1 filter routes paid Substacks to it
3. Last 7 days has ≥1 message under that label (otherwise first run sends "no newsletters" email)

**Blocks:** M5.7 smoke test only.

---

## Q-6. Existing `notify-episode.yml` — remove or leave dormant?

**Spec default:** Delete in M5.4.

**Alternative:** Leave the YAML in place but disable its trigger (set `on: workflow_dispatch` only, never auto). Useful as an emergency fallback if Resend fails.

**Recommendation:** Delete. Two ways to send email = two paths to maintain. If Resend fails for a week, we can re-add Gmail SMTP fallback then.

**Blocks:** Nothing — this is a cleanup task.

---

## Non-questions (resolved by defaults)

These were in scope to potentially flag but have stable defaults — not blocking:

- **Cron timezone** — `0 6 * * 5` UTC = 2 AM ET, lands before Fayad wakes Friday. Locked.
- **Length cap** — none. Locked.
- **Voices** — same as AI Industry. Locked.
- **Action item count** — exactly 3. Locked.
- **State retention** — 30 days of message IDs. Sensible default; tweak later if needed.
- **Slack alert channel** — `#inbox`, matches Fayad's existing pattern.

---

## To unblock: Fayad answers Q-1, Q-2, Q-3 (Q-3 only if Q-1 = A) before M4 starts. Q-5 must be confirmed before M5.7 smoke test.
