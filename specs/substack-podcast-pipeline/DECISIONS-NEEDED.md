# Decisions Needed Before Implementation

Three flags surfaced by the spec-builder. Each blocks part of M4 (email module) or M3 (memory injection). Resolve before kicking off the build.

---

## 1. Email transport: Resend vs. extend existing Gmail SMTP

**Status:** Spec defaults to Resend per locked design, but the existing repo uses Gmail SMTP with an app password (`notify-episode.yml`). Original assumption that Resend was already wired up was wrong.

**Trade-off:**
- **Resend (spec default)** — Markdown→HTML rendering is cleaner, audit log via Resend dashboard, free tier well within volume needs (~8 sends/month). Adds one dependency and one secret (`RESEND_API_KEY`). Required if you want professional-looking email with reliable deliverability.
- **Extend Gmail SMTP** — Zero new dependencies, reuses the existing app password and template pattern. Less polished HTML rendering. Risk: Google has been deprecating app passwords for some account types; if it breaks, OAuth migration is forced anyway.

**Recommendation:** Resend. The marginal setup cost (~10 min — sign up, get API key, add secret) buys deliverability + rendering quality + insulation from Google's app-password drift. Worth it for two weekly emails you'll actually read.

**Decision needed:** Resend or extend Gmail SMTP?

---

## 2. Resend sender domain

**Status:** Only relevant if Decision 1 = Resend.

**Trade-off:**
- **`podcasts.fayadabbasi.com`** — Real domain, professional sender, requires DNS work (SPF, DKIM, DMARC records on the domain). Sets you up for any future email needs from this domain.
- **`onboarding@resend.dev` (Resend sandbox)** — Zero setup. Works only when sending to email addresses you've verified in Resend (you're the only recipient — fits perfectly). Sender shows as Resend's domain, not yours.

**Recommendation:** Sandbox for v1. You're the only recipient; sender domain doesn't matter. Add custom domain later only if you decide to send to others.

**Decision needed:** Sandbox or custom domain?

---

## 3. Memory slice source for action-item prompt

**Status:** The 3 action items are memory-injected — the prompt pulls your role + current projects from somewhere. The "where" is the open question.

**Trade-off:**
- **Committed files in repo (`prompts/context/role.md` + `projects.md`)** — Single source of truth, version-controlled, deterministic, audit-able. Updates require a PR (slight friction; positive forcing function).
- **Private gist** — Edit anywhere without a PR; pipeline fetches at runtime. Friction-free updates, but adds an external dependency, runtime fetch can fail, and gist URL becomes a secret to manage.

**Recommendation:** Committed files. PR friction is a feature, not a bug — every change to your "who I am to the prompt" file is logged. The gist option is shaped like convenience but adds a failure mode (network call at runtime) for negligible upside.

**Decision needed:** Committed files or private gist?

---

## How to respond

Reply with three answers (e.g., "1: Resend, 2: sandbox, 3: committed files"). Spec-builder will update `01-design.md`, `04-config-and-secrets.md`, and `02-plan.md` accordingly before any implementation begins.
