# Promo Parser

Two-stage local promo-deal pipeline over your Gmail **Promotions**:

1. **Part 1 (`scripts/run.py`)** — fetch last 7 days of Promotions → classify
   against `interest_profile.yaml` → write `results/run_*.jsonl`.
2. **Part 2 (`scripts/verify.py`)** — for promising offers, agentic loop
   (Qwen3.6 + Tavily web search) checks if the deal is genuine and the product
   is good → write `results/verified_*.jsonl`.

Code lives in the `promo_parser/` package; `scripts/` holds thin CLI wrappers.
Each stage can also be launched with `python -m promo_parser.cli.<run|verify>`.

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
python scripts/run.py          # or: python -m promo_parser.cli.run
```

- First run opens a browser for Gmail consent and caches `token.json`
  (scope is read-only).
- Results land in `results/run_YYYY-MM-DD.jsonl`, one offer per line.
- Processed message IDs are tracked in `seen_ids.json`, so re-runs are
  idempotent. Emails that failed analysis are *not* marked seen and will be
  retried on the next run.

Useful flags:

```bash
python scripts/run.py --limit 10    # process at most 10 new emails (good first test)
python scripts/run.py --dry-run     # analyze but don't write results or mark seen
python scripts/run.py -v            # verbose (DEBUG) logging: per-message detail, prompts, timings
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
python scripts/verify.py       # or: python -m promo_parser.cli.verify
```

What it does:

1. Load the latest `results/run_*.jsonl`
2. Skip `verdict=skip` offers
3. Verify each `must_see` / `maybe` offer with Qwen3.6 + Tavily
4. Write `results/verified_YYYY-MM-DD.jsonl`

Useful variants:

```bash
python scripts/verify.py --input results/run_2026-07-12.jsonl   # explicit input
python scripts/verify.py --limit 3 --dry-run                    # smoke test, no write
python scripts/verify.py --limit 3                              # smoke test that writes
python scripts/verify.py --limit 3 -v                           # verbose: tool calls, searches, timings
```

Expect the first offer to take a while while the model loads. Per offer, the
model searches for price and review evidence, then calls a `submit_verdict`
tool to stop once it has enough (capped at `MAX_VERIFY_ITERS` rounds). A full
run can take many minutes.

### Verification engine (`--engine`)

Part 2 has two interchangeable engines, selected with `--engine` (default set by
`VERIFY_ENGINE` in `config.py`):

- `manual` (default) — the hand-rolled tool loop in `promo_parser/verify/`. No
  extra dependencies.
- `agno` — the same single-agent design built on the [Agno](https://github.com/agno-agi/agno)
  framework, which runs the tool loop and structured extraction for you. Opt-in
  and requires an extra install:

```bash
pip install -r requirements-agno.txt
python scripts/verify.py --engine agno --limit 3 -v
```

Both reuse the same prompt, `VerificationVerdict` schema, search client, and the
`passed` gate, so you can compare their output on the same offers. Verdicts will
differ somewhat because Agno adds its own prompt scaffolding.

## Logging

Both commands log progress to the console (stderr). By default you get
INFO-level output: startup config, per-email / per-offer results, and a final
summary. Add `-v` / `--verbose` for DEBUG detail — message fetches, prompt
sizes, each search query and result count, per-turn tool calls, the loop's
stop reason, and timings for the model/search calls.

```bash
python scripts/run.py -v        # or: python scripts/verify.py -v
python scripts/verify.py -v 2> verify.log     # tee/redirect since logs go to stderr
```

Log lines look like `HH:MM:SS LEVEL module | message`, e.g.
`14:57:25 DEBUG verify.verifier | model called submit_verdict -> enough evidence, ending loop`.

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
| `scripts/run.py`, `scripts/verify.py` | Thin CLI wrappers (add repo root to `sys.path`) |
| `promo_parser/config.py` | Paths, model names, Gmail query, verification settings |
| `promo_parser/models.py` | Pydantic schemas (offers + verification) |
| `promo_parser/gmail/client.py` | OAuth + fetching/parsing Promotions emails |
| `promo_parser/analyze/analyzer.py` | Part 1: prompt, Ollama call, validation with one retry |
| `promo_parser/analyze/ollama_check.py` | Preflight: Ollama up + model loads |
| `promo_parser/storage/storage.py` | `seen_ids.json` + results / verified JSONL |
| `promo_parser/cli/run.py` | Part 1 CLI (`main()`) |
| `promo_parser/verify/search.py` | Part 2: Tavily web search wrapper |
| `promo_parser/verify/verifier.py` | Part 2: agentic verification loop (manual engine) |
| `promo_parser/verify_agno/verifier.py` | Part 2: Agno-based engine (optional, `--engine agno`) |
| `promo_parser/cli/verify.py` | Part 2 CLI (`main()`, `--engine manual|agno`) |
| `requirements-agno.txt` | Optional deps for the Agno engine |
