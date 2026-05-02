# 06 — Retro

**Date:** 2026-05-02
**Scope:** M1–M5 of the substack-podcast-pipeline spec, end-to-end through first successful smoke test.
**Outcome:** Pipeline live. Episode `site/substack/episodes/episode_2026-05-02.mp3` (~30 min, 32MB) + email digest delivered + state file persisted, all on a single `workflow_dispatch` run. Auto-commit `cf165f6`.

---

## Outcome at a glance

| Metric | Value |
|---|---|
| Milestones planned | 5 (M1–M5) |
| Milestones shipped in code | 5 (M5.7 / M5.8 are user actions) |
| Commits | 8 on `feat/substack-pm-podcast` + main |
| Tests at end | 173 (started at 88) |
| Smoke-test iterations | 3 (2 failed, 1 succeeded) |
| Spec deviations | 3, all noted in commit messages |
| Decisions deferred or skipped | 2 of 3 from `DECISIONS-NEEDED.md` (Resend + sender domain), made moot by SMTP path |

---

## What worked

### 1. Spec-first, decisions-first
The `specs/substack-podcast-pipeline/` set was already in place when implementation started. The `DECISIONS-NEEDED.md` made the three blocking choices (SMTP vs Resend, sender domain, memory slice source) explicit and resolvable in a single back-and-forth before any code landed. Zero rebuilds caused by late clarification.

### 2. Milestone-sized commits
Each of M1–M5 landed as a single, scoped commit with the full test suite green at every step. When smoke-test #1 failed at Stage 2, knowing which commit introduced summarize_one made the fix surgical instead of speculative.

### 3. Test-first against mocked APIs
The mocked Anthropic/Gmail tests caught most validation, retry, and branching logic before any real API call. By smoke-test time, the unknowns were narrowed to actual model output behavior — exactly the things mocks can't catch.

### 4. Render-first preview
`/tmp/email_preview.py` rendered both digest types to local HTML before any SMTP wiring. Confirmed the email shape was right *before* spending an hour on OAuth + workflow setup. If the preview had revealed a bad layout, fixing it pre-deploy would have saved a smoke-test iteration.

### 5. Skip-on-failure pattern
When smoke-test #1 died on a single bad newsletter, the spec already prescribed the right fix ("body parse fails for 1 item → skip + log + continue"). Extending that pattern to summarize failures was a 10-line change that turned a fragile pipeline into a tolerant one.

### 6. Diagnostic-before-fix discipline
The first instinct on smoke-test #1 was "loosen the validator." Instead, the change was "log *why* the validator rejected." That gave smoke-test #2 a concrete signal — "model overshoots by 1–12 chars on six newsletters" — which made the actual fix evidence-based and right-sized.

### 7. Spec deviations called out, not buried
Three deviations from the spec landed (M2.3 ingest shim skipped, lazy imports flattened, AI Industry email simplified to no-aggregate). Each was named in its commit message with the reason. Easy to revisit later if any prove wrong.

### 8. Tight smoke-test feedback loop
Hotfixes went direct-to-main rather than via PR. For trivial validator/timeout adjustments during active iteration, the PR overhead would have been larger than the fix. (For M1–M5 itself, the PR was the right call — a real review surface.)

---

## What didn't work / lessons

### 1. The spec assumed an architecture component that didn't exist
The original spec was written assuming Resend was already wired in. It wasn't — the existing notify path was Gmail SMTP. This surfaced at decision #1 but only because we asked. **Lesson:** before locking architecture against an existing system, grep the codebase to verify the prereq actually exists. Spec assumptions decay.

### 2. The `one_liner` cap was tuned against a use that didn't exist
The 140-char cap was specified as "the hook a reader needs to decide" — but the field is **never rendered in the email digest**. Six newsletters were dropped in smoke-test #2 over a constraint that didn't affect any output. **Lesson:** when you constrain output, make sure the constraint comes from a real downstream rendering need, not aspirational design. Validators that don't trace to a rendered field are aspirational, not correctness checks.

### 3. Workflow timeout copy-pasted without scaling for content volume
The substack workflow inherited `timeout-minutes: 20` from the AI Industry workflow, which produces ~20 min of audio. Substack at 14 newsletters produces ~60 min of audio, which needs ~30 min of TTS wall-clock. The timeout fired mid-TTS on smoke-test #2 because nobody scaled the budget for the content delta. **Lesson:** when copying timing from a parallel workflow, multiply by the content-volume ratio.

### 4. Action item quality is gated on memory slices nobody filled in
`prompts/context/role.md` and `projects.md` shipped as empty templates. The action_items prompt validates count + URL + minutes range — but doesn't validate *quality*. So generic action items pass the validator and ship. The first email's actions read as filler. **Lesson:** content prerequisites for prompts should be gating, not "fill in later." Should have either filled in role.md/projects.md before merge, or added a CI check that fails the build if context files are still at the template default.

### 5. Initial smoke-test path didn't account for GitHub UI behavior
The first instruction was "trigger workflow_dispatch from the feature branch in the Actions UI." GitHub Actions doesn't show workflows in the sidebar unless they're on the default branch — that wasted ~15 min of confusion before merging the PR to main. **Lesson:** when planning a smoke-test trigger, walk the UI flow on paper first. Distinguish "the workflow file exists somewhere" from "GitHub recognizes it as a runnable workflow."

### 6. Vendor UI guides went stale faster than expected
The spec's Gmail OAuth section (`04-config-and-secrets.md`) referenced "APIs & Services → OAuth consent screen." Google moved that to a new "Google Auth Platform" with five sub-tabs sometime between spec authorship and execution. Live retrofitting the steps cost some momentum. **Lesson:** for vendor-UI walkthroughs, expect to retrofit. Capture the *intent* (what to configure) more durably than the click path.

### 7. AI Industry email shipped thin
The spec wanted "per-story summaries + aggregate" for AI Industry, but AI Industry has no aggregate prompt. We shipped per-story-only and called it "future enhancement." That's fine, but it means the AI Industry email is meaningfully less useful than the Substack one for no architectural reason. **Lesson:** parity gaps that look small in code can feel large in the artifact users actually see. Worth scoping in for v1.5 rather than letting the asymmetry settle.

### 8. Silent data-loss case in `MAX_NEWSLETTERS_PER_RUN` cap
The cap drops the *oldest* if more than 10 arrive in a week. Capped items aren't added to seen_ids so they get a chance next run — *but* they may fall out of the 7-day `newer_than` window before the next cron fires, in which case they're silently lost. This tradeoff was accepted under time pressure during smoke-test #2 and isn't documented in the design doc. **Lesson:** write down design tradeoffs at the moment of accepting them, not at retro time. Future-me will not remember why this was OK.

### 9. Long initial explainer when a one-paragraph recommendation would have done
When asked about Resend vs SMTP, the response was a 5-paragraph analysis. The user picked SMTP off the recommendation and didn't need the rest. **Lesson:** lead with the recommendation. Provide the analysis only if the user pulls on it.

---

## Process notes

- **Bugs caught in unit tests that wouldn't have surfaced in smoke test:** many — retry semantics, validator branches, mark_processed ordering, channel_config wiring. Tests earned their cost.
- **Bugs caught in smoke test that weren't caught in unit tests:** 2 — `one_liner` cap mismatch (model behavior) and TTS timeout (real-world timing). Both were unknowable from mocks alone.
- **Lines of test added vs production:** roughly 2:1, weighted toward integration/wiring tests over isolated units. Felt right for this domain.
- **Time from "all M5 code committed" to "first successful production run":** ~3 hours of smoke-test iteration. Most spent waiting for OAuth setup + watching workflow runs hit the timeout.

---

## What I'd do differently next time

1. **Prereq sweep before architectural decisions.** Before locking on Resend (or any spec-stated prereq), grep the codebase for what's actually wired. Update the spec or detour the design *before* downstream work depends on the wrong assumption.

2. **Validators must trace to rendered output.** Any constraint on a field's shape (length, type, regex) should reference the downstream consumer that needs the constraint. Aspirational caps belong in the prompt, not the validator.

3. **Workflow timeouts come from test runs, not estimates.** First real run should set the timeout (current_runtime × 1.5 ceiling). The 20-min copy-paste from AI Industry was lazy.

4. **Content prereqs are gating.** `role.md` / `projects.md` should have been filled in (with sample-or-real content) before the first cron-triggered run. Better still: add a CI check that fails if context files are at template-default state.

5. **For smoke-tests, walk the UI flow before describing it.** The "trigger from feature branch" instruction would have been caught with a 30-second mental rehearsal of the Actions tab.

6. **Lead with recommendations, expand on request.** Five-paragraph tradeoff analyses are useful sometimes, but the default should be one-sentence pick + one-sentence why + offer to dig in. The user can pull on it.

7. **Document accepted-tradeoff decisions at decision time.** The `MAX_NEWSLETTERS_PER_RUN` silent-data-loss case is a design decision that took two minutes to reason through and 30 seconds to write down. Should have been written down then, not at retro.

---

## Carryover items (real, not punch-list)

These came up during the build and are genuinely unresolved:

- **`role.md` / `projects.md` still empty.** Action items stay generic until filled in.
- **AI Industry email asymmetry.** Has stories but no aggregate paragraph. Either add an aggregate prompt for AI Industry or accept and document the asymmetry.
- **Two consecutive Friday cron runs needed** before flipping the pipeline status from "smoke-tested" to "production-stable" in personal MEMORY.md (per Fayad's "verify persistence" rule).
- **Cap-window data-loss in high-backlog weeks.** Currently undocumented in `01-design.md`. Should land there as a known tradeoff, or get a follow-up design pass if it bites.

---

*This retro is the third document in the spec set written after-the-fact. The first two — `00-brainstorming.md` and `DECISIONS-NEEDED.md` — captured the design phase. This one captures what survived contact with reality.*
