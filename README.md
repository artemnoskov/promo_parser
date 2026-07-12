# Promo Parser — MVP Part 1 (Inbox to JSONL)

Fetches the last 7 days of your Gmail **Promotions** category, has a local
Qwen model (via Ollama) judge each email against your interest profile, and
appends the validated offers to a JSONL file. No database, no scheduling —
run it manually.

```
Gmail (readonly) → pre-filter → Qwen (single-shot JSON) → Pydantic → results/*.jsonl
```

First time here? Follow the detailed walkthrough in
[GETTING_STARTED.md](GETTING_STARTED.md) — it covers the Google Cloud OAuth
setup, Ollama, the first run, and troubleshooting.

## Prerequisites

1. **Google Cloud OAuth client** (one-time):
   - Create a project at <https://console.cloud.google.com/>, enable the **Gmail API**.
   - Configure the OAuth consent screen (External, add yourself as a test user).
   - Create an **OAuth client ID** of type *Desktop app* and download the JSON
     as `credentials.json` into this directory.
2. **Ollama** with a Qwen model pulled:

   ```bash
   ollama pull qwen3.6:35b-a3b   # or whatever tag you use; set it in config.py
   ```

3. **Python deps**:

   ```bash
   python -m venv .venv && source .venv/bin/activate
   pip install -r requirements.txt
   ```

## Run

```bash
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

## Inspect results

```bash
jq . results/run_*.jsonl                                        # everything
jq 'select(.verdict == "must_see")' results/run_*.jsonl         # the good stuff
jq -s 'sort_by(-.score) | .[] | {title, merchant, score}' results/run_*.jsonl
```

## Tune

Edit `interest_profile.yaml` (interests, brands, never-list, price rules,
scoring rubric) and re-run. Bump its `version` when you change it — each
offer records the profile version that produced it.

## Files

| File | Purpose |
|---|---|
| `config.py` | Paths, model name, Gmail query |
| `models.py` | Pydantic schema the LLM must return |
| `gmail_client.py` | OAuth + fetching/parsing Promotions emails |
| `analyzer.py` | Prompt, Ollama call, validation with one retry |
| `storage.py` | `seen_ids.json` + JSONL append |
| `run.py` | CLI entrypoint |
