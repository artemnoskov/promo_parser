"""File-based storage: seen message IDs + append-only JSONL results."""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path

import config
from gmail_client import Email
from models import Offer, VerifiedOffer


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


# --- Verification stage (Part 2) ---

def verified_path_for_today() -> Path:
    return config.RESULTS_DIR / f"verified_{date.today().isoformat()}.jsonl"


def latest_results_file() -> Path | None:
    """Most recent results/run_*.jsonl, or None if there are none."""
    files = sorted(config.RESULTS_DIR.glob("run_*.jsonl"))
    return files[-1] if files else None


def load_offers(path: Path) -> list[dict]:
    """Read an offers JSONL file into a list of dicts."""
    offers: list[dict] = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                offers.append(json.loads(line))
    return offers


def append_verified(path: Path, verified: VerifiedOffer) -> None:
    """Append one verified-offer row (offer + verification + passed)."""
    config.RESULTS_DIR.mkdir(exist_ok=True)
    now = datetime.now(timezone.utc).isoformat()
    record = {
        **verified.offer,
        "verification": verified.verification.model_dump(mode="json"),
        "passed": verified.passed,
        "verifier_model": config.VERIFIER_MODEL,
        "verified_at": now,
    }
    with open(path, "a") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
