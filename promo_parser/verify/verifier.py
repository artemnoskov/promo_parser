"""Agentic deal-verification loop.

For one offer, lets a local reasoning model (qwen3.6) call web-search tools to
gather price/quality evidence. The model signals it has enough evidence by
calling the `submit_verdict` tool, which ends the loop; a final
schema-constrained call then emits a valid VerificationVerdict. The loop is
also bounded by MAX_VERIFY_ITERS as a safety ceiling, and falls back to
stopping if the model simply returns no tool calls.
"""

from __future__ import annotations

import json
import logging
import time

from ollama import Client
from ollama._types import ResponseError
from pydantic import ValidationError

from promo_parser import config
from promo_parser.models import VerificationVerdict
from promo_parser.verify.search import SearchClient, SearchError

log = logging.getLogger(__name__)

SYSTEM_PROMPT = """\
You verify whether a shopping deal is worth a user's attention.

You have tools to search the web. Use them to gather evidence, then decide:
1. is_genuine: is the discount/deal real, or fake / off an inflated "list price"?
   Use find_price_info to compare against the typical selling price.
2. quality_score (0.0-1.0): is the product actually good? Use find_reviews to
   check ratings and reviews.

Guidance:
- Call find_price_info / find_reviews to gather evidence. Do not rely on the
  merchant's own claims.
- Base every conclusion on retrieved evidence; cite it. Do not invent facts.
- If evidence is thin or conflicting, be conservative (lower quality_score,
  is_genuine=false when a discount cannot be corroborated).
- You have enough evidence once you have at least one credible price data point
  AND at least one review/quality source. Keep searching while either is missing.
- The moment you have enough to decide, call submit_verdict exactly once to stop.
  Do not keep searching after that.
"""

FINAL_INSTRUCTION = (
    "Based on the evidence gathered, return the final verification verdict now "
    "as JSON matching the schema. Include the evidence you relied on."
)

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "find_price_info",
            "description": (
                "Search the web for the typical/current price of a product to "
                "judge whether a discount is real. Returns search results."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "product": {
                        "type": "string",
                        "description": "Product name and merchant, e.g. 'Sony a7 IV B&H'",
                    }
                },
                "required": ["product"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "find_reviews",
            "description": (
                "Search the web for reviews and ratings of a product to judge "
                "its quality. Returns search results."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "product": {
                        "type": "string",
                        "description": "Product name to look up reviews for",
                    }
                },
                "required": ["product"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "submit_verdict",
            "description": (
                "Call this exactly once when you have enough evidence to decide "
                "(at least one credible price source AND one review/quality "
                "source). It signals you are done gathering evidence; the final "
                "structured verdict is produced afterwards. Do not search again "
                "after calling this."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "reason": {
                        "type": "string",
                        "description": "Brief note on why the evidence is sufficient",
                    }
                },
                "required": [],
            },
        },
    },
]

# Control-signal tool: not a search; calling it ends the evidence-gathering loop.
DECIDE_TOOL = "submit_verdict"


class VerificationError(Exception):
    """Raised when the model cannot produce a valid verdict."""


def _run_tool(search: SearchClient, name: str, args: dict) -> list[dict]:
    product = args.get("product", "")
    log.debug("Tool call: %s(product=%r)", name, product)
    if name == "find_price_info":
        return search.find_price_info(product)
    if name == "find_reviews":
        return search.find_reviews(product)
    raise VerificationError(f"Unknown tool: {name!r}")


def _build_user_prompt(offer: dict, profile: dict) -> str:
    fields = {
        k: offer.get(k)
        for k in (
            "title", "merchant", "category", "discount_text",
            "discount_pct", "price_text", "currency", "url",
        )
    }
    return (
        "Verify this offer.\n"
        f"OFFER: {json.dumps(fields, ensure_ascii=False)}\n\n"
        f"USER INTERESTS: {profile.get('interests')}\n"
        f"PRICE RULES: {profile.get('price_rules')}"
    )


def verify_offer(
    client: Client, search: SearchClient, offer: dict, profile: dict
) -> VerificationVerdict:
    """Run the bounded agentic loop for one offer and return a verdict."""
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": _build_user_prompt(offer, profile)},
    ]

    for iteration in range(1, config.MAX_VERIFY_ITERS + 1):
        log.debug("Loop iteration %d/%d", iteration, config.MAX_VERIFY_ITERS)
        started = time.perf_counter()
        try:
            resp = client.chat(
                model=config.VERIFIER_MODEL,
                messages=messages,
                tools=TOOLS,
                options={"temperature": 0.1},
            )
        except ResponseError as e:
            raise VerificationError(f"Ollama request failed: {e}") from e

        msg = resp["message"]
        tool_calls = msg.get("tool_calls") or []
        log.debug(
            "  model turn took %.1fs, requested %d tool call(s)",
            time.perf_counter() - started, len(tool_calls),
        )
        # Fallback: a model that simply stops calling tools is also "done".
        if not tool_calls:
            log.debug("  no tool calls -> ending loop (fallback stop)")
            break

        messages.append(msg)
        decided = False
        for call in tool_calls:
            fn = call["function"]
            name = fn["name"]
            args = fn.get("arguments") or {}
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except json.JSONDecodeError:
                    args = {}
            if name == DECIDE_TOOL:
                # Explicit "enough evidence" signal: acknowledge and stop after
                # this turn. Not routed through _run_tool (it is not a search).
                log.debug("  model called %s -> enough evidence, ending loop", DECIDE_TOOL)
                decided = True
                messages.append(
                    {"role": "tool", "name": name, "content": "acknowledged"}
                )
                continue
            try:
                results = _run_tool(search, name, args)
                content = json.dumps(results, ensure_ascii=False)
            except SearchError as e:
                log.warning("  search error in %s: %s", name, e)
                content = f"SEARCH_ERROR: {e}"
            messages.append(
                {"role": "tool", "name": name, "content": content}
            )

        # Model explicitly decided it has enough evidence -> leave the loop.
        if decided:
            break
    else:
        log.debug("Reached MAX_VERIFY_ITERS (%d) without an explicit decision",
                  config.MAX_VERIFY_ITERS)

    return _extract_verdict(client, messages)


def _extract_verdict(client: Client, messages: list) -> VerificationVerdict:
    """Final schema-constrained call to force a valid verdict."""
    messages = messages + [{"role": "user", "content": FINAL_INSTRUCTION}]
    schema = VerificationVerdict.model_json_schema()
    log.debug("Extracting final structured verdict")
    started = time.perf_counter()
    try:
        resp = client.chat(
            model=config.VERIFIER_MODEL,
            messages=messages,
            format=schema,
            options={"temperature": 0.1},
        )
    except ResponseError as e:
        raise VerificationError(f"Verdict extraction failed: {e}") from e

    content = resp["message"]["content"]
    log.debug("Verdict extraction took %.1fs", time.perf_counter() - started)
    try:
        return VerificationVerdict.model_validate_json(content)
    except ValidationError as e:
        raise VerificationError(f"Invalid verdict JSON: {e}") from e
