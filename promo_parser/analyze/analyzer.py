"""Single-shot LLM analysis of one email against the interest profile."""

from __future__ import annotations

import logging
import time

import yaml
from ollama import Client
from ollama._types import ResponseError
from pydantic import ValidationError

from promo_parser import config
from promo_parser.gmail.client import Email
from promo_parser.models import EmailAnalysis

log = logging.getLogger(__name__)

SYSTEM_PROMPT = """\
You judge promotional emails against a user's interest profile.

Return ONLY a JSON object matching the provided schema: {"offers": [...]}.
Each offer needs: title, score (0.0-1.0 per the profile's scoring rubric),
verdict ("must_see", "maybe" or "skip"), and a one-line reason. Fill the
other fields (merchant, category, discount_text, discount_pct, price_text,
currency, expires_at as an ISO date, url, image_url) when the email contains
them; use null when it does not.

Rules:
- Apply the profile's price rules and never_interested_in list strictly.
- One email may contain several distinct offers; list each separately.
- If nothing in the email is relevant to the profile, return {"offers": []}.
- Do not invent offers, prices or dates that are not in the email.
"""

RETRY_NUDGE = (
    "Your previous reply was not valid JSON for the schema. "
    "Respond again with ONLY the JSON object, no prose."
)


class AnalysisError(Exception):
    """Raised when the model fails to produce valid output after a retry."""


def load_profile() -> dict:
    log.debug("Loading interest profile from %s", config.PROFILE_PATH)
    with open(config.PROFILE_PATH) as f:
        return yaml.safe_load(f)


def _build_user_prompt(profile: dict, email: Email) -> str:
    profile_text = yaml.safe_dump(profile, sort_keys=False)
    body = email.body[: config.MAX_BODY_CHARS]
    return (
        f"USER PROFILE:\n{profile_text}\n"
        f"EMAIL:\nFrom: {email.sender}\n"
        f"Subject: {email.subject}\n"
        f"Date: {email.received_at}\n\n"
        f"{body}"
    )


def analyze_email(client: Client, profile: dict, email: Email) -> EmailAnalysis:
    """Run one single-shot analysis; retry once on invalid JSON.

    Raises AnalysisError if the model fails twice.
    """
    user_prompt = _build_user_prompt(profile, email)
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]
    schema = EmailAnalysis.model_json_schema()
    log.debug(
        "Analyzing message %s with %s (prompt %d chars)",
        email.message_id, config.OLLAMA_MODEL, len(user_prompt),
    )

    last_error: Exception | None = None
    for attempt in range(2):
        started = time.perf_counter()
        try:
            resp = client.chat(
                model=config.OLLAMA_MODEL,
                messages=messages,
                format=schema,
                options={"temperature": 0.1},
            )
        except ResponseError as e:
            raise AnalysisError(
                f"Ollama request failed for message {email.message_id}: {e}"
            ) from e
        elapsed = time.perf_counter() - started
        content = resp["message"]["content"]
        log.debug(
            "chat attempt %d for %s took %.1fs (%d chars returned)",
            attempt + 1, email.message_id, elapsed, len(content or ""),
        )
        try:
            analysis = EmailAnalysis.model_validate_json(content)
            log.debug(
                "Parsed %d offer(s) from %s on attempt %d",
                len(analysis.offers), email.message_id, attempt + 1,
            )
            return analysis
        except ValidationError as e:
            last_error = e
            log.warning(
                "Invalid JSON from model for %s on attempt %d; %s",
                email.message_id, attempt + 1,
                "retrying" if attempt == 0 else "giving up",
            )
            messages.append({"role": "assistant", "content": content})
            messages.append({"role": "user", "content": RETRY_NUDGE})

    raise AnalysisError(
        f"Model returned invalid JSON twice for message {email.message_id}: {last_error}"
    )
