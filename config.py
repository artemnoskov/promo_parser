"""Central configuration for the promo parser MVP."""

import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent

load_dotenv(BASE_DIR / ".env")

# --- Gmail ---
CREDENTIALS_PATH = BASE_DIR / "credentials.json"
TOKEN_PATH = BASE_DIR / "token.json"
GMAIL_SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]
GMAIL_QUERY = "category:promotions newer_than:7d"
MAX_EMAILS_PER_RUN = 200

# --- LLM (Ollama) ---
OLLAMA_MODEL = "qwen2.5:7b"  # adjust to the tag you pulled, e.g. `ollama list`
OLLAMA_HOST = "http://localhost:11434"

# --- Verification (Part 2) ---
# Reasoning model for the deal-verification agentic loop. Kept separate from
# OLLAMA_MODEL so classification and verification can use different models.
VERIFIER_MODEL = "qwen3.6:35b-a3b"
# Web search provider for gathering price/quality evidence.
SEARCH_PROVIDER = "tavily"
TAVILY_API_KEY = os.getenv("TAVILY_API_KEY", "")
# Max tool-call iterations per offer before forcing a best-effort verdict.
MAX_VERIFY_ITERS = 3
# An offer "passes" if it is genuine and quality_score >= this threshold.
QUALITY_THRESHOLD = 0.6
# How many search results to feed the model per tool call.
SEARCH_MAX_RESULTS = 5

# --- Profile ---
PROFILE_PATH = BASE_DIR / "interest_profile.yaml"

# --- Storage ---
RESULTS_DIR = BASE_DIR / "results"
SEEN_IDS_PATH = BASE_DIR / "seen_ids.json"

# Truncate very long email bodies before sending to the model (chars).
MAX_BODY_CHARS = 8000
