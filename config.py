"""Central configuration for the promo parser MVP."""

from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

# --- Gmail ---
CREDENTIALS_PATH = BASE_DIR / "credentials.json"
TOKEN_PATH = BASE_DIR / "token.json"
GMAIL_SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]
GMAIL_QUERY = "category:promotions newer_than:7d"
MAX_EMAILS_PER_RUN = 200

# --- LLM (Ollama) ---
OLLAMA_MODEL = "qwen3.6:35b-a3b"  # adjust to the tag you pulled, e.g. `ollama list`
OLLAMA_HOST = "http://localhost:11434"

# --- Profile ---
PROFILE_PATH = BASE_DIR / "interest_profile.yaml"

# --- Storage ---
RESULTS_DIR = BASE_DIR / "results"
SEEN_IDS_PATH = BASE_DIR / "seen_ids.json"

# Truncate very long email bodies before sending to the model (chars).
MAX_BODY_CHARS = 8000
