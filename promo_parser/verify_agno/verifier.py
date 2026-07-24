"""Agno-based deal-verification engine (parallel to promo_parser.verify).

Same contract as the hand-rolled loop: given one offer, gather price/quality
evidence via web search and return a ``VerificationVerdict``. The difference is
that the Agno ``Agent`` runs the tool-calling loop and the final schema-typed
extraction for us (via ``output_schema``), instead of the manual ``for``-loop +
``_extract_verdict`` in :mod:`promo_parser.verify.verifier`.

``agno`` is an optional dependency, imported lazily so the default (manual)
engine never requires it. Install with ``pip install -r requirements-agno.txt``.
"""

from __future__ import annotations

import logging
import time

from promo_parser import config
from promo_parser.models import VerificationVerdict
from promo_parser.verify.search import SearchClient
# Reuse the exact prompt, user-prompt builder, and error type so the two
# engines are compared apples-to-apples (no duplicated prompt text).
from promo_parser.verify.verifier import (
    SYSTEM_PROMPT,
    VerificationError,
    _build_user_prompt,
)

log = logging.getLogger(__name__)


def _import_agno():
    """Import Agno lazily; raise a clear, actionable error if it is missing."""
    try:
        from agno.agent import Agent
        from agno.models.ollama import Ollama
    except ImportError as e:
        raise VerificationError(
            "The 'agno' package is required for --engine agno. Install it with:\n"
            "  pip install -r requirements-agno.txt"
        ) from e
    return Agent, Ollama


def verify_offer(
    offer: dict,
    profile: dict,
    *,
    search: SearchClient,
    host: str | None = None,
) -> VerificationVerdict:
    """Verify one offer with an Agno single agent; return a VerificationVerdict.

    Mirrors :func:`promo_parser.verify.verifier.verify_offer` but delegates the
    tool loop and structured extraction to Agno. Raises ``VerificationError`` on
    a missing dependency, a failed run, or non-schema output.
    """
    Agent, Ollama = _import_agno()
    host = host or config.OLLAMA_HOST

    # Tools close over the injected SearchClient. Agno derives each tool's
    # schema from the function name, docstring, and type hints.
    def find_price_info(product: str) -> list[dict]:
        """Search the web for the typical/current price of a product to judge
        whether a discount is real. Returns search results."""
        return search.find_price_info(product)

    def find_reviews(product: str) -> list[dict]:
        """Search the web for reviews and ratings of a product to judge its
        quality. Returns search results."""
        return search.find_reviews(product)

    agent = Agent(
        model=Ollama(
            id=config.VERIFIER_MODEL,
            host=host,
            options={"temperature": 0.1},
        ),
        tools=[find_price_info, find_reviews],
        # NOTE: Agno's tool_call_limit is a soft limit (see agno issues
        # #6984 / #8304); the manual engine's range() bound is a hard cap.
        tool_call_limit=config.MAX_VERIFY_ITERS,
        output_schema=VerificationVerdict,
        instructions=SYSTEM_PROMPT,
        use_json_mode=True,
    )

    title = (offer.get("title") or "")[:60]
    log.debug("Agno engine: running agent for %r (model %s)", title, config.VERIFIER_MODEL)
    started = time.perf_counter()
    try:
        resp = agent.run(_build_user_prompt(offer, profile))
    except Exception as e:  # normalize any agno/model/runtime error
        raise VerificationError(f"Agno agent run failed: {e}") from e
    log.debug("Agno run took %.1fs", time.perf_counter() - started)

    content = getattr(resp, "content", None)
    # With local Ollama models, native schema output may be unavailable and
    # Agno's JSON fallback can leave content as a raw string on parse failure.
    if not isinstance(content, VerificationVerdict):
        raise VerificationError(
            "Agno returned non-schema output "
            f"(type {type(content).__name__}): {str(content)[:200]}"
        )
    return content
