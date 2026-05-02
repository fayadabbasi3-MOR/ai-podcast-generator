"""One-time bootstrap: open a browser, sign in to Gmail, capture a refresh token.

Run this from the repo root with `client_secret.json` (downloaded from GCP)
in the same directory:

    python scripts/gmail_oauth_bootstrap.py

The script prints three values to stdout. Copy each into a GitHub repository
secret:
  - GMAIL_OAUTH_CLIENT_ID
  - GMAIL_OAUTH_CLIENT_SECRET
  - GMAIL_OAUTH_REFRESH_TOKEN

After the secrets are set, delete the local `client_secret.json` (it contains
the same client_id + client_secret values, and is gitignored anyway):

    rm client_secret.json

Re-run this script if the refresh token ever stops working — Google revokes
refresh tokens that go unused for 6+ months, or if the OAuth consent screen
flips back to Testing mode.
"""

import json
import sys
from pathlib import Path

from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]
CLIENT_SECRET_PATH = Path(__file__).resolve().parent.parent / "client_secret.json"


def main() -> None:
    if not CLIENT_SECRET_PATH.exists():
        print(
            f"ERROR: expected {CLIENT_SECRET_PATH} to exist.\n"
            f"Download the OAuth 2.0 client JSON from GCP Console → APIs & "
            f"Services → Credentials → your OAuth client → Download JSON, then "
            f"save it as `client_secret.json` in the repo root.",
            file=sys.stderr,
        )
        sys.exit(1)

    with CLIENT_SECRET_PATH.open() as f:
        client_data = json.load(f).get("installed", {})
    client_id = client_data.get("client_id", "")
    client_secret = client_data.get("client_secret", "")

    flow = InstalledAppFlow.from_client_secrets_file(str(CLIENT_SECRET_PATH), SCOPES)
    print("\nOpening your browser for Google sign-in...")
    print("Sign in as fayadabbasi3@gmail.com and approve readonly Gmail access.\n")

    creds = flow.run_local_server(
        port=0,
        prompt="consent",          # forces refresh_token even on re-runs
        access_type="offline",     # ensures refresh_token is returned
    )

    if not creds.refresh_token:
        print(
            "ERROR: no refresh token returned. Most likely cause: this Gmail "
            "account has previously authorized this OAuth client and Google "
            "skipped consent. Revoke the existing grant at "
            "https://myaccount.google.com/permissions and re-run.",
            file=sys.stderr,
        )
        sys.exit(1)

    print("\n" + "=" * 70)
    print("SUCCESS — copy these three values into GitHub repository secrets")
    print("=" * 70)
    print(f"\nGMAIL_OAUTH_CLIENT_ID:\n{client_id}\n")
    print(f"GMAIL_OAUTH_CLIENT_SECRET:\n{client_secret}\n")
    print(f"GMAIL_OAUTH_REFRESH_TOKEN:\n{creds.refresh_token}\n")
    print("=" * 70)
    print("After adding all three to GH secrets, delete the local file:")
    print("    rm client_secret.json")
    print("=" * 70)


if __name__ == "__main__":
    main()
