"""CLI entrypoint for the deal-verification loop (Part 2).

Reads offers from a results JSONL, and for each non-skip offer runs the agentic
verification loop (local reasoning model + web search) to judge whether the
deal is genuine and the product is good. Writes results/verified_*.jsonl.

Usage:
    python scripts/verify.py [--input PATH] [--limit N] [--dry-run] [--engine {manual,agno}]
    python -m promo_parser.cli.verify [--input PATH] [--limit N] [--dry-run] [--engine {manual,agno}]
"""

from __future__ import annotations

import argparse
import logging
import sys
import time

from ollama import Client

from promo_parser import config
from promo_parser.storage import storage
from promo_parser.analyze.analyzer import load_profile
from promo_parser.models import VerifiedOffer
from promo_parser.analyze.ollama_check import check_ollama
from promo_parser.verify.search import SearchClient, SearchError
from promo_parser.verify.verifier import VerificationError, verify_offer as manual_verify_offer
from promo_parser.verify_agno.verifier import verify_offer as agno_verify_offer
from promo_parser.logging_setup import setup_logging

log = logging.getLogger(__name__)

# Offers with these verdicts are worth spending verification effort on.
VERIFY_VERDICTS = {"must_see", "maybe"}


def main() -> None:
    parser = argparse.ArgumentParser(description="Promo parser verification (Part 2)")
    parser.add_argument(
        "--input", type=str, default=None,
        help="results JSONL to verify (default: latest results/run_*.jsonl)",
    )
    parser.add_argument(
        "--limit", type=int, default=None,
        help="verify at most N offers (useful for a first test)",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="verify but do not write the verified JSONL",
    )
    parser.add_argument(
        "--engine", choices=("manual", "agno"), default=config.VERIFY_ENGINE,
        help="verification engine (default: %(default)s); 'agno' needs "
             "requirements-agno.txt installed",
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true",
        help="verbose (DEBUG) logging: per-iteration tool calls, searches, timings",
    )
    args = parser.parse_args()
    setup_logging(args.verbose)

    log.info(
        "Starting Part 2 (verify) [engine: %s]%s",
        args.engine, " [DRY RUN]" if args.dry_run else "",
    )
    input_path = _resolve_input(args.input)
    profile = load_profile()
    offers = storage.load_offers(input_path)
    log.debug("Loaded %d offer(s) from %s", len(offers), input_path)

    ollama = Client(host=config.OLLAMA_HOST)
    log.info("Checking Ollama at %s (model %s)", config.OLLAMA_HOST, config.VERIFIER_MODEL)
    check_ollama(ollama, model=config.VERIFIER_MODEL)
    log.debug("Ollama preflight OK")
    search = SearchClient()
    log.info("Checking search provider (%s)", config.SEARCH_PROVIDER)
    _preflight_search(search)
    log.debug("Search preflight OK")

    # Uniform per-offer callable so the loop/logging/summary below are
    # engine-agnostic. Both return a VerificationVerdict / raise VerificationError.
    if args.engine == "agno":
        def verify_fn(offer: dict):
            return agno_verify_offer(offer, profile, search=search, host=config.OLLAMA_HOST)
    else:
        def verify_fn(offer: dict):
            return manual_verify_offer(ollama, search, offer, profile)

    out_path = storage.verified_path_for_today()
    to_verify = sum(1 for o in offers if o.get("verdict") in VERIFY_VERDICTS)
    log.info(
        "Input: %s (%d offers, %d to verify) | engine: %s | verifier: %s | max iters: %d%s",
        input_path.name, len(offers), to_verify, args.engine, config.VERIFIER_MODEL,
        config.MAX_VERIFY_ITERS, " | DRY RUN" if args.dry_run else "",
    )

    n_verified = n_passed = n_errors = n_skipped = 0
    processed = 0

    for offer in offers:
        if offer.get("verdict") not in VERIFY_VERDICTS:
            n_skipped += 1
            log.debug("Skipping (verdict=%s) %r", offer.get("verdict"), (offer.get("title") or "")[:60])
            continue
        if args.limit is not None and processed >= args.limit:
            log.info("Reached --limit of %d offer(s); stopping early", args.limit)
            break
        processed += 1

        title = (offer.get("title") or "")[:60]
        log.info("[%d/%d] Verifying %r (merchant=%s)", processed, to_verify, title, offer.get("merchant") or "?")
        started = time.perf_counter()
        try:
            verdict = verify_fn(offer)
        except VerificationError as e:
            n_errors += 1
            log.error("[%d] Verification failed for %r: %s", processed, title, e)
            continue
        elapsed = time.perf_counter() - started

        passed = verdict.is_genuine and verdict.quality_score >= config.QUALITY_THRESHOLD
        n_verified += 1
        if passed:
            n_passed += 1

        if not args.dry_run:
            storage.append_verified(
                out_path,
                VerifiedOffer(offer=offer, verification=verdict, passed=passed),
            )

        flag = "PASS" if passed else "fail"
        log.info(
            "[%d] [%s] genuine=%s quality=%.2f (%d evidence, %.1fs) %r",
            processed, flag, verdict.is_genuine, verdict.quality_score,
            len(verdict.evidence), elapsed, title,
        )
        log.debug("[%d] authenticity: %s", processed, verdict.authenticity_reason)
        log.debug("[%d] quality: %s", processed, verdict.quality_reason)

    log.info(
        "Run summary: %d verified | %d passed | %d errors | %d skipped (verdict=skip)",
        n_verified, n_passed, n_errors, n_skipped,
    )
    if not args.dry_run and n_verified:
        log.info("Verified: %s", out_path)
        log.info("Survivors: jq 'select(.passed)' %s", out_path)


def _resolve_input(arg: str | None):
    if arg:
        from pathlib import Path
        path = Path(arg)
        if not path.exists():
            sys.exit(f"Input file not found: {path}")
        log.debug("Using explicit input file %s", path)
        return path
    latest = storage.latest_results_file()
    if latest is None:
        sys.exit("No results/run_*.jsonl found. Run run.py first, or pass --input.")
    log.debug("Using latest results file %s", latest)
    return latest


def _preflight_search(search: SearchClient) -> None:
    try:
        search.find_price_info("connectivity check")
    except SearchError as e:
        sys.exit(f"Search provider not ready: {e}")


if __name__ == "__main__":
    main()
