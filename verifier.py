"""Agentic deal-verification loop.

For one offer, lets a local reasoning model (qwen3.6) call web-search tools to
gather price/quality evidence, then emits a structured VerificationVerdict.
The loop is bounded by MAX_VERIFY_ITERS; the final verdict is extracted with a
schema-constrained call so it is always valid JSON.
"""

from __future__ import annotations

import json

from ollama import Client
from ollama._types import ResponseError
from pydantic import ValidationError

import config
from models import VerificationVerdict
from search_client import SearchClient, SearchError

SYSTEM_PROMPT = """\
You verify whether a shopping deal is worth a user's attention.

You have tools to search the web. Use them to gather evidence, then decide:
1. is_genuine: is the discount/deal real, or fake / off an inflated "list price"?
   Use find_price_info to compare against the typical selling price.
2. quality_score (0.0-1.0): is the product actually good? Use find_reviews to
   check ratings and reviews.

Guidance:
- Call tools before judging. Do not rely on the merchant's own claims.
- Base every conclusion on retrieved evidence; cite it. Do not invent facts.
- If evidence is thin or conflicting, be conservative (lower quality_score,
  is_genuine=false when a discount cannot be corroborated).
- When done gathering evidence, stop calling tools and give your verdict.
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
]


class VerificationError(Exception):
    """Raised when the model cannot produce a valid verdict."""


def _run_tool(search: SearchClient, name: str, args: dict) -> list[dict]:
    product = args.get("product", "")
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

    for _ in range(config.MAX_VERIFY_ITERS):
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
        if not tool_calls:
            break

        messages.append(msg)
        for call in tool_calls:
            fn = call["function"]
            name = fn["name"]
            args = fn.get("arguments") or {}
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except json.JSONDecodeError:
                    args = {}
            try:
                results = _run_tool(search, name, args)
                content = json.dumps(results, ensure_ascii=False)
            except SearchError as e:
                content = f"SEARCH_ERROR: {e}"
            messages.append(
                {"role": "tool", "name": name, "content": content}
            )

    return _extract_verdict(client, messages)


def _extract_verdict(client: Client, messages: list) -> VerificationVerdict:
    """Final schema-constrained call to force a valid verdict."""
    messages = messages + [{"role": "user", "content": FINAL_INSTRUCTION}]
    schema = VerificationVerdict.model_json_schema()
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
    try:
        return VerificationVerdict.model_validate_json(content)
    except ValidationError as e:
        raise VerificationError(f"Invalid verdict JSON: {e}") from e
