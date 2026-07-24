"""Web search wrapper for the verification loop.

Exposes two focused helpers - find_price_info and find_reviews - that return a
list of {title, url, snippet} dicts. Only the product title/merchant is ever
sent to the search API; raw email content never leaves the machine here.
"""

from __future__ import annotations

import logging
import time

from promo_parser import config

log = logging.getLogger(__name__)


class SearchError(Exception):
    """Raised when the search provider is misconfigured or unreachable."""


class SearchClient:
    """Thin wrapper over a web search provider (default: Tavily)."""

    def __init__(self, provider: str | None = None, api_key: str | None = None):
        self.provider = provider or config.SEARCH_PROVIDER
        self.api_key = api_key if api_key is not None else config.TAVILY_API_KEY
        self._client = None

    def _get_client(self):
        if self._client is not None:
            return self._client
        if self.provider != "tavily":
            raise SearchError(f"Unsupported search provider: {self.provider!r}")
        if not self.api_key:
            raise SearchError(
                "TAVILY_API_KEY is not set. Add it to .env (see .env.example)."
            )
        try:
            from tavily import TavilyClient
        except ImportError as e:
            raise SearchError(
                "tavily-python not installed. Run: pip install -r requirements.txt"
            ) from e
        self._client = TavilyClient(api_key=self.api_key)
        return self._client

    def _search(self, query: str) -> list[dict]:
        client = self._get_client()
        log.debug("Search (%s): %r", self.provider, query)
        started = time.perf_counter()
        try:
            resp = client.search(
                query=query,
                max_results=config.SEARCH_MAX_RESULTS,
                search_depth="basic",
            )
        except Exception as e:  # provider-specific errors vary; normalize them
            raise SearchError(f"Search failed for {query!r}: {e}") from e
        results = [
            {
                "title": r.get("title", ""),
                "url": r.get("url", ""),
                "snippet": r.get("content", ""),
            }
            for r in resp.get("results", [])
        ]
        log.debug(
            "Search returned %d result(s) in %.1fs for %r",
            len(results), time.perf_counter() - started, query,
        )
        return results

    def find_price_info(self, product: str) -> list[dict]:
        """Search for typical/current price to judge if a discount is real."""
        return self._search(f"{product} price")

    def find_reviews(self, product: str) -> list[dict]:
        """Search for reviews/ratings to judge product quality."""
        return self._search(f"{product} review rating")
