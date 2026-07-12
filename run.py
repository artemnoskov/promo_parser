"""CLI entrypoint: fetch Promotions, analyze with Qwen, write JSONL results.

Usage:
    python run.py [--limit N] [--dry-run]
"""

from __future__ import annotations

import argparse
import sys

from ollama import Client

import config
import gmail_client
import storage
from analyzer import AnalysisError, analyze_email, load_profile


def main() -> None:
    parser = argparse.ArgumentParser(description="Promo parser MVP (Part 1)")
    parser.add_argument(
        "--limit", type=int, default=None,
        help="process at most N new emails (useful for a first test)",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="analyze but do not write results or mark emails as seen",
    )
    args = parser.parse_args()

    profile = load_profile()
    profile_version = str(profile.get("version", "unknown"))
    seen = storage.load_seen_ids()
    ollama = Client(host=config.OLLAMA_HOST)

    print(f"Query: {config.GMAIL_QUERY!r} | model: {config.OLLAMA_MODEL} "
          f"| profile v{profile_version}{' | DRY RUN' if args.dry_run else ''}")

    service = gmail_client.get_service()
    message_ids = gmail_client.list_message_ids(service)
    print(f"Fetched {len(message_ids)} message ids "
          f"({sum(1 for m in message_ids if m in seen)} already seen)")

    n_analyzed = n_offers = n_errors = n_skipped_empty = 0
    processed = 0

    for msg_id in message_ids:
        if msg_id in seen:
            continue
        if args.limit is not None and processed >= args.limit:
            break
        processed += 1

        email = gmail_client.fetch_email(service, msg_id)
        if not email.body.strip() and not email.snippet.strip():
            n_skipped_empty += 1
            seen.add(msg_id)
            continue

        try:
            analysis = analyze_email(ollama, profile, email)
        except AnalysisError as e:
            # Not marked seen -> will be retried on the next run.
            n_errors += 1
            print(f"  ERROR {email.subject[:60]!r}: {e}", file=sys.stderr)
            continue

        n_analyzed += 1
        if analysis.offers:
            n_offers += len(analysis.offers)
            if not args.dry_run:
                storage.append_offers(email, analysis.offers, profile_version)
            top = max(analysis.offers, key=lambda o: o.score)
            print(f"  {len(analysis.offers)} offer(s) "
                  f"[best: {top.verdict.value} {top.score:.2f}] "
                  f"{email.subject[:60]!r}")
        else:
            print(f"  no offers  {email.subject[:60]!r}")

        seen.add(msg_id)

    if not args.dry_run:
        storage.save_seen_ids(seen)

    print(
        f"\nRun summary: {len(message_ids)} fetched | {n_analyzed} analyzed | "
        f"{n_offers} offers | {n_errors} errors | {n_skipped_empty} empty-skipped"
    )
    if not args.dry_run and n_offers:
        print(f"Results: {storage.results_path_for_today()}")


if __name__ == "__main__":
    main()
