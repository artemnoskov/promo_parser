"""Gmail read-only client: OAuth with token cache + fetching Promotions emails."""

from __future__ import annotations

import base64
import logging
import sys
from dataclasses import dataclass

from bs4 import BeautifulSoup
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

from promo_parser import config

log = logging.getLogger(__name__)


@dataclass
class Email:
    message_id: str
    thread_id: str
    sender: str
    subject: str
    received_at: str  # RFC 2822 date header as-is
    snippet: str
    body: str


def get_service():
    """Return an authenticated Gmail API service, running OAuth if needed."""
    creds = None
    if config.TOKEN_PATH.exists():
        log.debug("Loading cached OAuth token from %s", config.TOKEN_PATH)
        creds = Credentials.from_authorized_user_file(
            str(config.TOKEN_PATH), config.GMAIL_SCOPES
        )

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            log.info("Refreshing expired Gmail OAuth token")
            creds.refresh(Request())
        else:
            if not config.CREDENTIALS_PATH.exists():
                sys.exit(
                    f"Missing {config.CREDENTIALS_PATH.name}. Download an OAuth "
                    "Desktop-app client JSON from Google Cloud Console (see README)."
                )
            log.info("No valid token; starting OAuth consent flow in your browser")
            flow = InstalledAppFlow.from_client_secrets_file(
                str(config.CREDENTIALS_PATH), config.GMAIL_SCOPES
            )
            creds = flow.run_local_server(port=0)
        config.TOKEN_PATH.write_text(creds.to_json())
        log.debug("Wrote refreshed token to %s", config.TOKEN_PATH)
    else:
        log.debug("Cached Gmail token is valid")

    return build("gmail", "v1", credentials=creds)


def list_message_ids(service, query: str = config.GMAIL_QUERY) -> list[str]:
    """List message IDs matching the query, paginating as needed."""
    log.debug("Listing message ids for query %r (cap %d)", query, config.MAX_EMAILS_PER_RUN)
    ids: list[str] = []
    page_token = None
    page = 0
    while True:
        resp = (
            service.users()
            .messages()
            .list(userId="me", q=query, maxResults=100, pageToken=page_token)
            .execute()
        )
        page += 1
        ids.extend(m["id"] for m in resp.get("messages", []))
        log.debug("  page %d: %d id(s) so far", page, len(ids))
        page_token = resp.get("nextPageToken")
        if not page_token or len(ids) >= config.MAX_EMAILS_PER_RUN:
            break
    return ids[: config.MAX_EMAILS_PER_RUN]


def fetch_email(service, message_id: str) -> Email:
    """Fetch one message and extract headers + a plaintext body."""
    msg = (
        service.users()
        .messages()
        .get(userId="me", id=message_id, format="full")
        .execute()
    )
    payload = msg.get("payload", {})
    headers = {h["name"].lower(): h["value"] for h in payload.get("headers", [])}

    return Email(
        message_id=msg["id"],
        thread_id=msg.get("threadId", ""),
        sender=headers.get("from", ""),
        subject=headers.get("subject", ""),
        received_at=headers.get("date", ""),
        snippet=msg.get("snippet", ""),
        body=_extract_body(payload),
    )


def _extract_body(payload: dict) -> str:
    """Prefer text/plain; fall back to text/html stripped to text."""
    plain = _find_part(payload, "text/plain")
    if plain:
        return plain
    html = _find_part(payload, "text/html")
    if html:
        log.debug("No text/plain part; falling back to stripped text/html")
        return BeautifulSoup(html, "html.parser").get_text(separator="\n", strip=True)
    log.debug("No text/plain or text/html body part found")
    return ""


def _find_part(part: dict, mime_type: str) -> str | None:
    """Depth-first search of the MIME tree for the first part of `mime_type`."""
    if part.get("mimeType") == mime_type:
        data = part.get("body", {}).get("data")
        if data:
            return base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")
    for sub in part.get("parts", []):
        found = _find_part(sub, mime_type)
        if found:
            return found
    return None
