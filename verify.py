"""CLI entrypoint for the deal-verification loop (Part 2).

Reads offers from a results JSONL, and for each non-skip offer runs the agentic
verification loop (local reasoning model + web search) to judge whether the
deal is genuine and the product is good. Writes results/verified_*.jsonl.

Usage:
    python verify.py [--input PATH] [--limit N] [--dry-run]
"""

from __future__ import annotations

import argparse
import sys

from ollama import Client

import config
import storage
from analyzer import load_profile
from models import VerificationVerdict, VerifiedOffer
from ollama_check import check_ollama
from search_client import SearchClient, SearchError
from verifier import VerificationError, verify_offer

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
    args = parser.parse_args()

    input_path = _resolve_input(args.input)
    profile = load_profile()
    offers = storage.load_offers(input_path)

    ollama = Client(host=config.OLLAMA_HOST)
    check_ollama(ollama, model=config.VERIFIER_MODEL)
    search = SearchClient()
    _preflight_search(search)

    out_path = storage.verified_path_for_today()
    print(f"Input: {input_path.name} ({len(offers)} offers) | "
          f"verifier: {config.VERIFIER_MODEL} | max iters: {config.MAX_VERIFY_ITERS}"
          f"{' | DRY RUN' if args.dry_run else ''}")

    n_verified = n_passed = n_errors = n_skipped = 0
    processed = 0

    for offer in offers:
        if offer.get("verdict") not in VERIFY_VERDICTS:
            n_skipped += 1
            continue
        if args.limit is not None and processed >= args.limit:
            break
        processed += 1

        title = (offer.get("title") or "")[:60]
        try:
            verdict = verify_offer(ollama, search, offer, profile)
        except VerificationError as e:
            n_errors += 1
            print(f"  ERROR {title!r}: {e}", file=sys.stderr)
            continue

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
        print(f"  [{flag}] genuine={verdict.is_genuine} "
              f"quality={verdict.quality_score:.2f} {title!r}")

    print(
        f"\nRun summary: {n_verified} verified | {n_passed} passed | "
        f"{n_errors} errors | {n_skipped} skipped (verdict=skip)"
    )
    if not args.dry_run and n_verified:
        print(f"Verified: {out_path}")
        print("Survivors: jq 'select(.passed)' " + str(out_path))


def _resolve_input(arg: str | None):
    if arg:
        from pathlib import Path
        path = Path(arg)
        if not path.exists():
            sys.exit(f"Input file not found: {path}")
        return path
    latest = storage.latest_results_file()
    if latest is None:
        sys.exit("No results/run_*.jsonl found. Run run.py first, or pass --input.")
    return latest


def _preflight_search(search: SearchClient) -> None:
    try:
        search.find_price_info("connectivity check")
    except SearchError as e:
        sys.exit(f"Search provider not ready: {e}")


if __name__ == "__main__":
    main()
