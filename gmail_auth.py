"""
Gmail API authentication helper for a local app.

Handles three cases automatically:
  1. First run: no token yet -> opens browser for you to authorize.
  2. Access token expired (normal, hourly): refreshes silently, no browser.
  3. Refresh token expired (weekly, while OAuth consent screen is in
     "Testing" status): automatically reopens the browser so you can
     re-approve, then keeps going.

SETUP (one-time):
  1. pip install google-auth-oauthlib google-api-python-client --break-system-packages
  2. In Google Cloud Console: Google Auth Platform -> Clients
     -> create (or use) an OAuth client with type "Desktop app"
  3. Download that client's JSON and save it as "credentials.json"
     in this same folder

USAGE in your app:
    from gmail_auth import get_gmail_service

    service = get_gmail_service()
    results = service.users().messages().list(userId="me").execute()
"""

import os

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

# Adjust to whatever Gmail scopes your app actually needs.
SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]

CREDENTIALS_FILE = "credentials.json"
TOKEN_FILE = "token.json"


def get_credentials():
    creds = None

    # Load previously saved token, if it exists.
    if os.path.exists(TOKEN_FILE):
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)

    # No valid credentials -> figure out whether we can refresh or must
    # re-authorize from scratch.
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                print("Access token expired, refreshing silently...")
                creds.refresh(Request())
            except Exception as e:
                # This is the weekly case: the refresh token itself has
                # expired (Testing mode) or been revoked.
                print(f"Refresh failed ({e}). Re-authorizing in browser...")
                creds = None

        if not creds:
            flow = InstalledAppFlow.from_client_secrets_file(
                CREDENTIALS_FILE, SCOPES
            )
            creds = flow.run_local_server(port=0)

        # Save the (possibly new) credentials for next time.
        with open(TOKEN_FILE, "w") as f:
            f.write(creds.to_json())

    return creds


def get_gmail_service():
    """Returns an authorized Gmail API service object, ready to use."""
    creds = get_credentials()
    return build("gmail", "v1", credentials=creds)


if __name__ == "__main__":
    # Quick manual test: authorize and print the first few messages.
    service = get_gmail_service()
    results = service.users().messages().list(userId="me", maxResults=5).execute()
    messages = results.get("messages", [])
    print(f"\nFound {len(messages)} messages. IDs: {[m['id'] for m in messages]}")
