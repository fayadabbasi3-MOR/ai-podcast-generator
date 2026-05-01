# 04 — Config, Secrets, One-Time Setup

## GitHub repository secrets

| Secret | Used by | How to obtain | Notes |
|---|---|---|---|
| `ANTHROPIC_API_KEY` | both workflows | console.anthropic.com → API keys | already exists |
| `GOOGLE_TTS_CREDENTIALS` | both workflows | GCP service account JSON, base64-encoded | already exists |
| `GMAIL_OAUTH_CLIENT_ID` | substack workflow | GCP OAuth 2.0 client ID (see §"Gmail OAuth setup") | NEW |
| `GMAIL_OAUTH_CLIENT_SECRET` | substack workflow | same OAuth 2.0 client | NEW |
| `GMAIL_OAUTH_REFRESH_TOKEN` | substack workflow | one-time local consent flow | NEW |
| `RESEND_API_KEY` | both workflows | resend.com → API keys | NEW |
| `RECIPIENT_EMAIL` | both workflows | `fayadabbasi3@gmail.com` | NEW |
| `SLACK_WEBHOOK_INBOX` | both workflows | Slack app → incoming webhook for `#inbox` | NEW |

The existing `notify-episode.yml` secrets (`GMAIL_SENDER`, `GMAIL_APP_PASSWORD`, `NOTIFY_EMAIL`) become unused after M5.4 deletes that workflow. Fayad can revoke `GMAIL_APP_PASSWORD` after both workflows are confirmed sending via Resend.

## Environment variables in workflow YAML

Every job needing the API:

```yaml
env:
  ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
  RESEND_API_KEY: ${{ secrets.RESEND_API_KEY }}
  RECIPIENT_EMAIL: ${{ secrets.RECIPIENT_EMAIL }}
  PAGES_BASE_URL: https://${{ github.repository_owner }}.github.io/${{ github.event.repository.name }}
```

Substack-only additions:

```yaml
  GMAIL_OAUTH_CLIENT_ID: ${{ secrets.GMAIL_OAUTH_CLIENT_ID }}
  GMAIL_OAUTH_CLIENT_SECRET: ${{ secrets.GMAIL_OAUTH_CLIENT_SECRET }}
  GMAIL_OAUTH_REFRESH_TOKEN: ${{ secrets.GMAIL_OAUTH_REFRESH_TOKEN }}
```

## `.env.example` additions

```
# Gmail (Substack PM Weekly only)
GMAIL_OAUTH_CLIENT_ID=
GMAIL_OAUTH_CLIENT_SECRET=
GMAIL_OAUTH_REFRESH_TOKEN=

# Resend (both podcasts)
RESEND_API_KEY=re_...
RECIPIENT_EMAIL=fayadabbasi3@gmail.com

# Slack alerting
SLACK_WEBHOOK_INBOX=https://hooks.slack.com/services/...
```

---

## Gmail OAuth setup (one-time, ~15 min)

This is the painful part. Do it once on a laptop with a browser; the refresh token then lives in GH secrets indefinitely.

### Step 1 — Enable Gmail API in GCP

1. Go to https://console.cloud.google.com → select existing project (the one already used for `GOOGLE_TTS_CREDENTIALS`) or create new.
2. APIs & Services → Library → search "Gmail API" → Enable.

### Step 2 — Create OAuth 2.0 client

1. APIs & Services → Credentials → Create Credentials → OAuth client ID.
2. Application type: **Desktop app**.
3. Name: `ai-podcast-generator-gmail`.
4. Download the JSON. Note `client_id` and `client_secret`.
5. APIs & Services → OAuth consent screen → if not configured: User Type = External, scopes = `https://www.googleapis.com/auth/gmail.readonly`, add Fayad's email as a test user.

### Step 3 — Generate refresh token (run locally, once)

Save this as `scripts/gmail_oauth_bootstrap.py` (one-time, gitignored):

```python
from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]
flow = InstalledAppFlow.from_client_secrets_file(
    "client_secret.json", SCOPES
)
creds = flow.run_local_server(port=0)
print("REFRESH TOKEN:", creds.refresh_token)
```

Run with `client_secret.json` (downloaded in Step 2) in the same directory:

```bash
python scripts/gmail_oauth_bootstrap.py
# Browser opens, sign in as fayadabbasi3@gmail.com, approve readonly access
# Refresh token prints to stdout
```

### Step 4 — Stash secrets in GitHub

Repo Settings → Secrets and variables → Actions → New repository secret. Add:
- `GMAIL_OAUTH_CLIENT_ID` = client_id from Step 2
- `GMAIL_OAUTH_CLIENT_SECRET` = client_secret from Step 2
- `GMAIL_OAUTH_REFRESH_TOKEN` = refresh token from Step 3

### Step 5 — Delete local artifacts

```bash
rm client_secret.json
rm scripts/gmail_oauth_bootstrap.py  # or commit it under scripts/, gitignored secrets
```

### Refresh token longevity

- A Google OAuth refresh token for a "Desktop app" client doesn't expire as long as it's used at least once every 6 months. Friday cron use is well within that.
- If the OAuth consent screen is in **Testing** mode (vs. Published), refresh tokens expire in **7 days**. **You must publish the consent screen** to get a non-expiring token. Publishing requires no Google review when scopes are `gmail.readonly` and there's only one user.

---

## Adding a new Substack to the inclusion list

**No code change required.** Fayad maintains the inclusion list via Gmail filter UI:

1. In Gmail, find a message from the new Substack publication.
2. Click overflow menu → Filter messages like these.
3. Set: from contains `<substack-publication-domain>` (e.g. `lennysnewsletter.com`).
4. Apply label: `Substack/PM`. (Create the label if it doesn't exist.)
5. Optionally: "Skip the Inbox" to keep inbox clean while still labeling.

Next Friday's cron picks it up automatically.

To **remove** a Substack: delete or edit the corresponding Gmail filter. The pipeline is purely consumer-side.

---

## Memory slice contents

These two files live in the repo at `prompts/context/` and are committed plain Markdown. Fayad updates them as projects shift. They get injected into the action_items prompt at runtime.

### `prompts/context/role.md`

Recommended starter content (Fayad to maintain — keep ≤30 lines):

```markdown
# Role

- **Title:** Product Manager, Developer Experience
- **Employer:** impact.com
- **Start date:** April 6, 2026 (currently in months 1–3 ramp; 60 hr/week guardrail, dropping to 50 hr/week from month 4)
- **Manager:** Logan — practices Radical Candor; 2-hour back-home debriefs are normal; APM hire conversation already in motion (week-3 trust signal)
- **Team methodology:** ShapeUp (6-week cycles, no sprints)
- **DX tooling stack:** Atlassian (Jira/Confluence) + Port (internal developer portal)
- **Org context:** Cape Town tech summit late April 2026 — debrief lane runs April–May
- **Psychology shorthand:** Enneagram 5w4. Drives via systems mastery + self-sufficiency. Trust is the friction point — once lost, hard to rebuild. God-mode at 2 AM.
- **Operating mode:** "Listen and learn" 30-day strategy: visual mapping (Miro/Lucid), backlog audits, metrics/tooling audits before proposing changes.
```

### `prompts/context/projects.md`

Recommended starter content (Fayad to maintain — keep ≤40 lines, prune as projects close):

```markdown
# Current Projects & Initiatives

## At impact.com (work)
- **Port tooling audit** — mapping current developer portal usage, identifying gaps
- **GitHub workflow setup** — onboarding to internal repos, CI/CD patterns, code review norms
- **Backlog audit** — reading Jira backlog deeply before opining
- **APM hire scoping** — Logan opened the conversation week 3; what to delegate, what to keep
- **Cape Town summit follow-ups** — relationships to maintain post-trip, action items from sessions
- **PM Workflow Setup (work laptop, Gemini CLI):** 60 slash commands, 21 skills, 10 plugins, MCPs (Figma, Miro, Slack, Jira) — separate system from Eve

## Brand & content (personal)
- **Goal:** 500 followers, 6–12 content pieces in 2026
- **Angle:** DevEx thought leadership — observations from the inside of a DX PM role
- **Cadence:** still TBD; weekly observation post is the floor

## Ongoing systems work (personal)
- **Eve evolution:** 5-phase arc — currently building "System" phase (scheduled rebuilds queued for 5/1 after 4/30 audit revealed all crons dead). GHA stack now preferred over Anthropic remote triggers.
- **Weekly planning protocol:** Sunday night sessions; reference docs, bootcamp pacing, brand integration

## Reading & learning
- **The Iliad re-read** — ongoing
- **impact.com book** — reading
- **Pragmatic Engineer (Gergely Orosz)** — subscribe queued
```

**Maintenance principle:** these slices should describe *current* projects only. When a project closes, delete its lines. The action items prompt should never see "PM Workflow Setup completed Q4 2025"-style historical context.
