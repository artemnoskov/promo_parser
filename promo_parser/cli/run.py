"""CLI entrypoint: fetch Promotions, analyze with Qwen, write JSONL results.

Usage:
    python scripts/run.py [--limit N] [--dry-run]
    python -m promo_parser.cli.run [--limit N] [--dry-run]
"""

from __future__ import annotations

import argparse
import logging

from ollama import Client

from promo_parser import config
from promo_parser.gmail import client as gmail_client
from promo_parser.storage import storage
from promo_parser.analyze.analyzer import AnalysisError, analyze_email, load_profile
from promo_parser.analyze.ollama_check import check_ollama
from promo_parser.logging_setup import setup_logging

log = logging.getLogger(__name__)


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
    parser.add_argument(
        "-v", "--verbose", action="store_true",
        help="verbose (DEBUG) logging: per-message detail, prompts, timings",
    )
    args = parser.parse_args()
    setup_logging(args.verbose)

    log.info("Starting Part 1 (classify)%s", " [DRY RUN]" if args.dry_run else "")
    profile = load_profile()
    profile_version = str(profile.get("version", "unknown"))
    log.debug("Loaded profile v%s from %s", profile_version, config.PROFILE_PATH)
    seen = storage.load_seen_ids()
    log.debug("Loaded %d already-seen message id(s)", len(seen))

    ollama = Client(host=config.OLLAMA_HOST)
    log.info("Checking Ollama at %s (model %s)", config.OLLAMA_HOST, config.OLLAMA_MODEL)
    check_ollama(ollama)
    log.debug("Ollama preflight OK")

    log.info(
        "Query: %r | model: %s | profile v%s%s",
        config.GMAIL_QUERY, config.OLLAMA_MODEL, profile_version,
        " | DRY RUN" if args.dry_run else "",
    )

    service = gmail_client.get_service()
    message_ids = gmail_client.list_message_ids(service)
    already = sum(1 for m in message_ids if m in seen)
    log.info("Fetched %d message id(s) (%d already seen)", len(message_ids), already)

    n_analyzed = n_offers = n_errors = n_skipped_empty = 0
    processed = 0

    for msg_id in message_ids:
        if msg_id in seen:
            log.debug("Skipping already-seen message %s", msg_id)
            continue
        if args.limit is not None and processed >= args.limit:
            log.info("Reached --limit of %d new email(s); stopping early", args.limit)
            break
        processed += 1

        log.debug("[%d] Fetching message %s", processed, msg_id)
        email = gmail_client.fetch_email(service, msg_id)
        log.debug(
            "[%d] %r | from=%s | body=%d chars, snippet=%d chars",
            processed, email.subject[:60], email.sender,
            len(email.body), len(email.snippet),
        )
        if not email.body.strip() and not email.snippet.strip():
            log.debug("[%d] Empty body and snippet; marking seen and skipping", processed)
            n_skipped_empty += 1
            seen.add(msg_id)
            continue

        try:
            analysis = analyze_email(ollama, profile, email)
        except AnalysisError as e:
            # Not marked seen -> will be retried on the next run.
            n_errors += 1
            log.error("[%d] Analysis failed for %r: %s", processed, email.subject[:60], e)
            continue

        n_analyzed += 1
        if analysis.offers:
            n_offers += len(analysis.offers)
            if not args.dry_run:
                storage.append_offers(email, analysis.offers, profile_version)
            top = max(analysis.offers, key=lambda o: o.score)
            log.info(
                "[%d] %d offer(s) [best: %s %.2f] %r",
                processed, len(analysis.offers), top.verdict.value, top.score,
                email.subject[:60],
            )
            for o in analysis.offers:
                log.debug(
                    "    - %s %.2f | %s | %s",
                    o.verdict.value, o.score, (o.merchant or "?"), o.title[:80],
                )
        else:
            log.info("[%d] no offers  %r", processed, email.subject[:60])

        seen.add(msg_id)

    if not args.dry_run:
        storage.save_seen_ids(seen)
        log.debug("Saved %d seen id(s) to %s", len(seen), config.SEEN_IDS_PATH)

    log.info(
        "Run summary: %d fetched | %d analyzed | %d offers | %d errors | %d empty-skipped",
        len(message_ids), n_analyzed, n_offers, n_errors, n_skipped_empty,
    )
    if not args.dry_run and n_offers:
        log.info("Results: %s", storage.results_path_for_today())


if __name__ == "__main__":
    main()
