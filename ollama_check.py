"""Ollama connectivity and model-load preflight checks."""

from __future__ import annotations

import sys

from ollama import Client
from ollama._types import ResponseError

import config


def check_ollama(client: Client | None = None, model: str | None = None) -> None:
    """Verify Ollama is reachable and the given model loads.

    Exits with a helpful message if not. Call once at startup before doing work.
    Defaults to config.OLLAMA_MODEL; pass `model` to check a different one
    (e.g. config.VERIFIER_MODEL).
    """
    client = client or Client(host=config.OLLAMA_HOST)
    model = model or config.OLLAMA_MODEL

    try:
        client.list()
    except Exception as e:
        sys.exit(
            "Cannot reach Ollama at "
            f"{config.OLLAMA_HOST!r}. Start it with:\n"
            "  brew services start ollama\n"
            "or open the Ollama app.\n"
            f"Details: {e}"
        )

    try:
        client.chat(
            model=model,
            messages=[{"role": "user", "content": "Reply with exactly: ok"}],
            stream=False,
            options={"num_predict": 4},
        )
    except ResponseError as e:
        msg = str(e).lower()
        if "unable to load model" in msg:
            sys.exit(
                f"Ollama cannot load model {model!r}.\n\n"
                "This usually means your Ollama version is too old for Qwen 3.6 "
                "(qwen35moe architecture). Fix:\n"
                "  1. Upgrade: brew upgrade ollama   (need 0.17+; 0.31+ recommended)\n"
                "  2. Restart: brew services restart ollama\n"
                "  3. Confirm: ollama --version && ollama run qwen3.6:35b-a3b hi\n\n"
                "Temporary workaround: set OLLAMA_MODEL = \"qwen2.5:7b\" in config.py\n"
                f"Details: {e}"
            )
        if "not found" in msg:
            sys.exit(
                f"Model {model!r} is not installed. Pull it with:\n"
                f"  ollama pull {model}\n"
                f"Details: {e}"
            )
        raise
