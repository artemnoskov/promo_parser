"""Pydantic schema for the LLM's structured output.

The field shape intentionally matches the future SQLite `offers` table
(Part 2), so switching the storage sink later requires no rework.
"""

from enum import Enum

from pydantic import BaseModel, Field


class Verdict(str, Enum):
    must_see = "must_see"
    maybe = "maybe"
    skip = "skip"


class Offer(BaseModel):
    title: str
    merchant: str | None = None
    category: str | None = None
    discount_text: str | None = None  # raw, e.g. "50% off"
    discount_pct: float | None = None  # parsed percentage if determinable
    price_text: str | None = None
    currency: str | None = None
    expires_at: str | None = None  # ISO date if found in the email
    url: str | None = None
    image_url: str | None = None  # best product image, if any
    score: float = Field(ge=0.0, le=1.0)
    verdict: Verdict
    reason: str


class EmailAnalysis(BaseModel):
    """What one Qwen call must return. Empty list = nothing relevant."""

    offers: list[Offer]
