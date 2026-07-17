# Promo Parser

Two-stage local promo-deal pipeline over your Gmail **Promotions**:

1. **Part 1 (`run.py`)** — fetch last 7 days of Promotions → classify against
   `interest_profile.yaml` → write `results/run_*.jsonl`.
2. **Part 2 (`verify.py`)** — for promising offers, agentic loop (Qwen3.6 +
   Tavily web search) checks if the deal is genuine and the product is good →
   write `results/verified_*.jsonl`.

No database, no scheduling — run it manually.

```
Gmail → Qwen classify → results/run_*.jsonl
                      → verify (Qwen3.6 + Tavily) → results/verified_*.jsonl
```

First time here? Follow the detailed walkthrough in
[GETTING_STARTED.md](GETTING_STARTED.md) — it covers the Google Cloud OAuth
setup, Ollama, the first run, and troubleshooting.

For a full layout of files and modules, see
[PROJECT_STRUCTURE.md](PROJECT_STRUCTURE.md).

For a step-by-step explanation of the pipeline and how the model/prompts work,
see [HOW_IT_WORKS.md](HOW_IT_WORKS.md).

## Prerequisites

1. **Google Cloud OAuth client** (one-time):
   - Create a project at <https://console.cloud.google.com/>, enable the **Gmail API**.
   - Configure the OAuth consent screen (External, add yourself as a test user).
   - Create an **OAuth client ID** of type *Desktop app* and download the JSON
     as `credentials.json` into this directory.
2. **Ollama** (need **0.17+**, **0.31+** recommended for Qwen 3.6):

   ```bash
   brew upgrade ollama && brew services restart ollama
   ollama pull qwen2.5:7b          # Part 1 classifier (OLLAMA_MODEL)
   ollama pull qwen3.6:35b-a3b     # Part 2 verifier  (VERIFIER_MODEL)
   ollama run qwen3.6:35b-a3b hi   # confirm it loads
   ```

3. **Python deps**:

   ```bash
   python -m venv .venv && source .venv/bin/activate
   pip install -r requirements.txt
   ```

4. **Tavily API key** (Part 2 only) — free key from <https://app.tavily.com/>:

   ```bash
   cp .env.example .env   # then set TAVILY_API_KEY=tvly-...
   ```

## Run Part 1 — classify

```bash
source .venv/bin/activate
python run.py
```

- First run opens a browser for Gmail consent and caches `token.json`
  (scope is read-only).
- Results land in `results/run_YYYY-MM-DD.jsonl`, one offer per line.
- Processed message IDs are tracked in `seen_ids.json`, so re-runs are
  idempotent. Emails that failed analysis are *not* marked seen and will be
  retried on the next run.

Useful flags:

```bash
python run.py --limit 10    # process at most 10 new emails (good first test)
python run.py --dry-run     # analyze but don't write results or mark seen
```

## Run Part 2 — verify (full)

Uses the newest `results/run_*.jsonl` by default. Needs Ollama with
`qwen3.6:35b-a3b` loaded and `TAVILY_API_KEY` in `.env`.

```bash
source .venv/bin/activate

# Make sure Ollama is up and the verifier model loads
brew services start ollama   # if not already running
ollama run qwen3.6:35b-a3b hi

# Full run → results/verified_YYYY-MM-DD.jsonl
python verify.py
```

What it does:

1. Load the latest `results/run_*.jsonl`
2. Skip `verdict=skip` offers
3. Verify each `must_see` / `maybe` offer with Qwen3.6 + Tavily
4. Write `results/verified_YYYY-MM-DD.jsonl`

Useful variants:

```bash
python verify.py --input results/run_2026-07-12.jsonl   # explicit input
python verify.py --limit 3 --dry-run                    # smoke test, no write
python verify.py --limit 3                              # smoke test that writes
```

Expect the first offer to take a while while the model loads. Each offer may
do up to 3 tool rounds (price + reviews searches). A full run can take many
minutes.

## Inspect results

```bash
# Part 1
jq . results/run_*.jsonl                                        # everything
jq 'select(.verdict == "must_see")' results/run_*.jsonl         # the good stuff
jq -s 'sort_by(-.score) | .[] | {title, merchant, score}' results/run_*.jsonl

# Part 2
jq 'select(.passed)' results/verified_*.jsonl
jq '{title, passed, is_genuine: .verification.is_genuine, quality: .verification.quality_score}' results/verified_*.jsonl
```

## Tune

Edit `interest_profile.yaml` (interests, brands, never-list, price rules,
scoring rubric) and re-run. Bump its `version` when you change it — each
offer records the profile version that produced it.

## Files

| File | Purpose |
|---|---|
| `HOW_IT_WORKS.md` | Step-by-step pipeline and model/prompt flow |
| `GETTING_STARTED.md` | First-time setup and troubleshooting |
| `PROJECT_STRUCTURE.md` | Full repo layout and module map |
| `config.py` | Paths, model names, Gmail query, verification settings |
| `models.py` | Pydantic schemas (offers + verification) |
| `gmail_client.py` | OAuth + fetching/parsing Promotions emails |
| `analyzer.py` | Part 1: prompt, Ollama call, validation with one retry |
| `storage.py` | `seen_ids.json` + results / verified JSONL |
| `run.py` | Part 1 CLI |
| `search_client.py` | Part 2: Tavily web search wrapper |
| `verifier.py` | Part 2: agentic verification loop |
| `verify.py` | Part 2 CLI |
