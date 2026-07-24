"""Console logging setup shared by the CLI entrypoints.

All package modules log via ``logging.getLogger(__name__)`` (names like
``promo_parser.verify.verifier``). Calling :func:`setup_logging` once at CLI
startup attaches a single stderr handler to the ``promo_parser`` parent logger,
so every child module's output is captured and formatted consistently.
"""

from __future__ import annotations

import logging
import sys

# ANSI colors keyed by level; only used when stderr is an interactive TTY.
_LEVEL_COLORS = {
    logging.DEBUG: "\033[90m",     # bright black / grey
    logging.INFO: "\033[36m",      # cyan
    logging.WARNING: "\033[33m",   # yellow
    logging.ERROR: "\033[31m",     # red
    logging.CRITICAL: "\033[1;31m",  # bold red
}
_RESET = "\033[0m"


class _ConsoleFormatter(logging.Formatter):
    """Shorten the ``promo_parser.`` prefix and optionally colorize the level."""

    def __init__(self, use_color: bool) -> None:
        super().__init__(
            fmt="%(asctime)s %(levelname)-5s %(short_name)-16s | %(message)s",
            datefmt="%H:%M:%S",
        )
        self.use_color = use_color

    def format(self, record: logging.LogRecord) -> str:
        record.short_name = record.name.replace("promo_parser.", "")
        if self.use_color:
            color = _LEVEL_COLORS.get(record.levelno, "")
            if color:
                record.levelname = f"{color}{record.levelname}{_RESET}"
        return super().format(record)


def setup_logging(verbose: bool = False) -> None:
    """Configure console logging for the whole ``promo_parser`` package.

    Args:
        verbose: when True, emit DEBUG-level detail; otherwise INFO and above.
    """
    level = logging.DEBUG if verbose else logging.INFO

    handler = logging.StreamHandler(stream=sys.stderr)
    handler.setFormatter(_ConsoleFormatter(use_color=sys.stderr.isatty()))

    root = logging.getLogger("promo_parser")
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)
    # Handled here; don't also bubble up to the (unconfigured) root logger.
    root.propagate = False


def get_logger(name: str) -> logging.Logger:
    """Return a package logger; ``name`` is usually ``__name__``."""
    return logging.getLogger(name)
