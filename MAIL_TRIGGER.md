# MAIL_TRIGGER Plan: Email Notification After Episode Publish

## Goal

Create a second GitHub Actions workflow that sends an email notification with the new episode URL after the podcast generation workflow completes successfully.

---

## Architecture

```
generate-episode.yml (existing)
        |
        | workflow_run trigger (on completion, success only)
        v
notify-episode.yml (new)
        |
        | 1. Checkout repo (to read feed.xml)
        | 2. Run scripts/notify_email.py
        |    - Parse site/feed.xml for latest episode URL
        |    - Send email via Gmail SMTP
        v
    Email delivered
```

---

## Files to Create

### 1. `scripts/notify_email.py`

**Purpose:** Send an email with the latest episode URL via Gmail SMTP.

**How it works:**
- Parse `site/feed.xml` using `lxml` (already a project dependency)
- Extract the most recent `<item>`: title, episode URL (from `<enclosure url="...">`), and publish date
- Connect to `smtp.gmail.com:587` using TLS
- Authenticate with sender address + App Password (from env vars)
- Send a simple email with subject line and body containing the episode link
- Uses only Python standard library (`smtplib`, `email`) plus `lxml` (already installed)

**Environment variables required:**
| Variable | Description |
|---|---|
| `GMAIL_SENDER` | Gmail address used to send the notification |
| `GMAIL_APP_PASSWORD` | Gmail App Password (not the account password) |
| `NOTIFY_EMAIL` | Recipient email address |

**Exit codes:**
- `0` — email sent successfully
- `1` — missing env vars, feed parse failure, or SMTP error (logged to stderr)

### 2. `.github/workflows/notify-episode.yml`

**Purpose:** Trigger email notification after successful episode generation.

**Trigger:**
```yaml
on:
  workflow_run:
    workflows: ["Generate Weekly Podcast Episode"]
    types: [completed]
```

**Job:**
- **Condition:** `if: github.event.workflow_run.conclusion == 'success'` — only notify on success, skip if the generate workflow failed
- **Steps:**
  1. Checkout repository (to access `site/feed.xml` and `scripts/notify_email.py`)
  2. Set up Python 3.12
  3. Install dependencies (`pip install lxml`)
  4. Run `python scripts/notify_email.py`

**Secrets required (3 new GitHub repo secrets):**
| Secret | Value |
|---|---|
| `GMAIL_SENDER` | Your Gmail address (e.g. `fayadabbasi3@gmail.com`) |
| `GMAIL_APP_PASSWORD` | App Password generated from Google account settings |
| `NOTIFY_EMAIL` | Recipient email address |

---

## Email Format

**Subject:** `New Episode: AI Industry Weekly — March 26, 2026`

**Body:**
```
A new podcast episode is available:

AI Industry Weekly — March 26, 2026

Listen: https://fayadabbasi.github.io/ai-podcast-generator/site/episodes/episode_2026-03-26.mp3

Feed: https://fayadabbasi.github.io/ai-podcast-generator/site/feed.xml
```

---

## Setup Steps (Manual, One-Time)

1. **Enable 2-Factor Authentication** on the Gmail account (if not already enabled)
2. **Generate an App Password:**
   - Go to https://myaccount.google.com/apppasswords
   - Select "Mail" and "Other (Custom name)" -> name it "Podcast Notifier"
   - Copy the 16-character password
3. **Add 3 secrets** to the GitHub repo (Settings > Secrets and variables > Actions):
   - `GMAIL_SENDER` = your Gmail address
   - `GMAIL_APP_PASSWORD` = the 16-character App Password
   - `NOTIFY_EMAIL` = recipient email address
4. **No code dependencies to add** — `smtplib` and `email` are in the Python standard library; `lxml` is already in `requirements.txt`

---

## Testing

- Trigger manually: run the `generate-episode.yml` workflow via `workflow_dispatch`, then verify the notify workflow fires and email arrives
- Test the script locally:
  ```bash
  GMAIL_SENDER=you@gmail.com GMAIL_APP_PASSWORD=xxxx NOTIFY_EMAIL=recipient@example.com python scripts/notify_email.py
  ```
  (requires `site/feed.xml` to exist with at least one episode)

---

## Summary of Changes

| File | Action |
|---|---|
| `scripts/notify_email.py` | **Create** — email notification script |
| `.github/workflows/notify-episode.yml` | **Create** — triggered workflow |
| GitHub repo secrets | **Add** 3 new secrets (manual) |
