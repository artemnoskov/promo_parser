"""File-based storage: seen message IDs + append-only JSONL results."""

from __future__ import annotations

import json
from datetime import date, datetime, timezone

import config
from gmail_client import Email
from models import Offer


def load_seen_ids() -> set[str]:
    if config.SEEN_IDS_PATH.exists():
        return set(json.loads(config.SEEN_IDS_PATH.read_text()))
    return set()


def save_seen_ids(seen: set[str]) -> None:
    config.SEEN_IDS_PATH.write_text(json.dumps(sorted(seen), indent=0))


def results_path_for_today():
    return config.RESULTS_DIR / f"run_{date.today().isoformat()}.jsonl"


def append_offers(
    email: Email, offers: list[Offer], profile_version: str
) -> None:
    """Append one JSON line per offer, enriched with provenance fields."""
    config.RESULTS_DIR.mkdir(exist_ok=True)
    now = datetime.now(timezone.utc).isoformat()
    with open(results_path_for_today(), "a") as f:
        for offer in offers:
            record = offer.model_dump(mode="json")
            record.update(
                {
                    "message_id": email.message_id,
                    "sender": email.sender,
                    "subject": email.subject,
                    "received_at": email.received_at,
                    "profile_version": profile_version,
                    "model": config.OLLAMA_MODEL,
                    "created_at": now,
                }
            )
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
