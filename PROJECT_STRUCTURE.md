# Project Structure

Overview of the **promo_parser** repository: what each file does, how modules
connect, and what gets created at runtime.

Two stages exist today:

- **Part 1** — inbox to JSONL (`promo_parser.cli.run`): fetch, classify, store
  offers.
- **Part 2** — deal verification (`promo_parser.cli.verify`): an agentic loop
  that checks whether promising offers are genuine and good, using a local
  reasoning model plus web search.

Code lives in the `promo_parser/` package (grouped into `gmail` / `analyze` /
`verify` / `storage` / `cli` subpackages); `scripts/` holds thin CLI wrappers.
Runtime files and secrets stay at the repo root. No database, no report
rendering, no scheduling yet.

## Directory tree

```
promo_parser/                     # repo root
├── README.md                     # Project overview and quick reference
├── GETTING_STARTED.md            # First-time setup and troubleshooting
├── HOW_IT_WORKS.md               # Step-by-step pipeline and model/prompt flow
├── PROJECT_STRUCTURE.md          # This file
├── requirements.txt              # Python dependencies
├── requirements-agno.txt         # Optional deps for the Agno verify engine
├── .env.example                  # Template for TAVILY_API_KEY
├── .gitignore
├── interest_profile.yaml         # Your interests, brands, scoring rules (editable)
│
├── scripts/                      # Convenience wrappers (add repo root to sys.path)
│   ├── run.py                    # → promo_parser.cli.run:main
│   └── verify.py                 # → promo_parser.cli.verify:main
│
└── promo_parser/                 # the package
    ├── __init__.py
    ├── config.py                 # Paths and constants (Gmail, Ollama, storage)
    ├── logging_setup.py          # Console logging config (shared by both CLIs)
    ├── models.py                 # Pydantic schemas the LLM must return
    ├── gmail/
    │   ├── __init__.py
    │   └── client.py             # Gmail OAuth + fetch/parse emails
    ├── analyze/
    │   ├── __init__.py
    │   ├── analyzer.py           # Prompt, Ollama call, validation + retry
    │   └── ollama_check.py       # Preflight: Ollama up + model loads
    ├── verify/                   # manual verify engine (default)
    │   ├── __init__.py
    │   ├── verifier.py           # Part 2 agentic verification loop (tools + model)
    │   └── search.py             # Web search wrapper (price/reviews evidence)
    ├── verify_agno/              # Agno verify engine (optional, --engine agno)
    │   ├── __init__.py
    │   └── verifier.py           # Same contract via an Agno single agent
    ├── storage/
    │   ├── __init__.py
    │   └── storage.py            # seen_ids.json + results/*.jsonl
    └── cli/
        ├── __init__.py
        ├── run.py                # Part 1 CLI (fetch → classify → store)
        └── verify.py             # Part 2 CLI (gate → verify → verified JSONL)
```

Naming note: entrypoints live in `promo_parser/cli/` because a `verify.py`
module cannot coexist with the `verify/` subpackage. Invoke as
`python -m promo_parser.cli.run` / `python -m promo_parser.cli.verify`, or via
the `scripts/` wrappers.

### Created at runtime (gitignored)

These files appear after you run the project. They live at the repo root (see
the `BASE_DIR` note below) and are not committed to git.

```
promo_parser/                      # repo root
├── credentials.json               # You download this from Google Cloud (one-time)
├── token.json                     # Cached Gmail OAuth token after first consent
├── .env                           # TAVILY_API_KEY for the verification stage
├── seen_ids.json                  # Message IDs already processed (idempotency)
├── results/
│   ├── run_YYYY-MM-DD.jsonl       # Part 1: one JSON object per offer
│   └── verified_YYYY-MM-DD.jsonl  # Part 2: offer + verification + passed
└── .venv/                         # Local Python virtual environment (optional)
```

### Path resolution (`config.BASE_DIR`)

`promo_parser/config.py` sits one level below the repo root, so it resolves
`BASE_DIR = Path(__file__).resolve().parent.parent`. That keeps
`credentials.json`, `token.json`, `.env`, `interest_profile.yaml`, and
`results/` anchored at the repo root regardless of where you launch from.

## Module map

| Module | Role |
|---|---|
| [scripts/run.py](scripts/run.py), [scripts/verify.py](scripts/verify.py) | Thin wrappers: add repo root to `sys.path`, call packaged `main()` |
| [cli/run.py](promo_parser/cli/run.py) | Part 1 CLI: wires fetch → filter → analyze → store; prints run summary |
| [cli/verify.py](promo_parser/cli/verify.py) | Part 2 CLI: gate offers → verify → write verified JSONL |
| [analyze/ollama_check.py](promo_parser/analyze/ollama_check.py) | Preflight: verify Ollama is up and a given model loads |
| [gmail/client.py](promo_parser/gmail/client.py) | OAuth, list/fetch Promotions, extract plaintext body |
| [analyze/analyzer.py](promo_parser/analyze/analyzer.py) | Build prompt from profile + email; call Ollama; validate JSON |
| [storage/storage.py](promo_parser/storage/storage.py) | Load/save `seen_ids.json`; append offers + verified rows to JSONL |
| [models.py](promo_parser/models.py) | `Offer`, `Verdict`, `EmailAnalysis`, `VerificationVerdict`, `VerifiedOffer` |
| [logging_setup.py](promo_parser/logging_setup.py) | `setup_logging(verbose)` — one stderr handler on the `promo_parser` logger |
| [config.py](promo_parser/config.py) | Single place for paths, model names, Gmail query, limits, verification settings |
| [verify/search.py](promo_parser/verify/search.py) | Part 2: web search wrapper (`find_price_info` / `find_reviews`) |
| [verify/verifier.py](promo_parser/verify/verifier.py) | Part 2: bounded agentic loop (tool-calling + structured verdict); the `manual` engine |
| [verify_agno/verifier.py](promo_parser/verify_agno/verifier.py) | Part 2: the `agno` engine (optional dep) reusing the same prompt/schema/search |

## Data flow

```
promo_parser.cli.run  (scripts/run.py)
  │
  ├─► gmail.client.get_service()     OAuth → Gmail API service
  ├─► gmail.client.list_message_ids()  q: category:promotions newer_than:7d
  │
  ├─► storage.load_seen_ids()        skip already-processed messages
  │
  └─► for each new message:
        gmail.client.fetch_email()   → Email dataclass
        analyze.analyzer.analyze_email() → EmailAnalysis (Pydantic)
          ├─ load_profile()          ← interest_profile.yaml
          └─ Ollama chat (JSON schema from models.EmailAnalysis)
        storage.append_offers()      → results/run_YYYY-MM-DD.jsonl
        storage.save_seen_ids()      → seen_ids.json
```

### Part 2 — verification (promo_parser.cli.verify)

```
promo_parser.cli.verify  (scripts/verify.py)
  │
  ├─► storage.latest_results_file()  pick newest results/run_*.jsonl
  ├─► storage.load_offers()          read offers to verify
  ├─► ollama_check(VERIFIER_MODEL)   preflight reasoning model
  ├─► SearchClient()                 web search (needs TAVILY_API_KEY)
  │
  ├─► pick engine (--engine, default config.VERIFY_ENGINE)
  │     ├─ manual → verify.verifier.verify_offer(ollama, search, offer, profile)
  │     └─ agno   → verify_agno.verifier.verify_offer(offer, profile, search=, host=)
  │
  └─► for each offer with verdict in {must_see, maybe}:
        verify_fn(offer)             → VerificationVerdict   (manual engine shown)
          ├─ loop (max MAX_VERIFY_ITERS):
          │    Ollama chat with tools (find_price_info / find_reviews / submit_verdict)
          │    ├─ search tool?    → run search → append evidence → repeat
          │    ├─ submit_verdict? → enough evidence → break
          │    └─ no tool?        → break (fallback)
          └─ final format-constrained call → VerificationVerdict
        passed = is_genuine and quality_score >= QUALITY_THRESHOLD
        storage.append_verified()    → results/verified_YYYY-MM-DD.jsonl
```

## File reference

### Documentation

- **[README.md](README.md)** — What the project does, prerequisites, run
  commands, `jq` examples, file index.
- **[GETTING_STARTED.md](GETTING_STARTED.md)** — Step-by-step first run: Google
  Cloud OAuth, Ollama, venv, dry-run, troubleshooting.
- **[HOW_IT_WORKS.md](HOW_IT_WORKS.md)** — Step-by-step pipeline flow and how
  the system prompt, profile, schema, and Ollama call fit together.
- **[PROJECT_STRUCTURE.md](PROJECT_STRUCTURE.md)** — Architecture and layout
  (this document).

### Configuration and profile

- **[config.py](promo_parser/config.py)** — Constants (loads `.env` via python-dotenv):
  - `BASE_DIR = parent.parent` so root-level files/secrets resolve at the repo root.
  - Gmail: `credentials.json`, `token.json`, readonly scope, search query,
    max emails per run.
  - Ollama: classifier model tag (`OLLAMA_MODEL`), host URL.
  - Verification: `VERIFY_ENGINE` (default engine), `VERIFIER_MODEL`,
    `SEARCH_PROVIDER`, `TAVILY_API_KEY`, `MAX_VERIFY_ITERS`,
    `QUALITY_THRESHOLD`, `SEARCH_MAX_RESULTS`.
  - Storage: `results/` directory, `seen_ids.json` path.
  - `MAX_BODY_CHARS` — truncates long email bodies before sending to the model.
- **[interest_profile.yaml](interest_profile.yaml)** — User-tunable input:
  `interests`, `brands_care_about`, `never_interested_in`, `price_rules`,
  `scoring_rubric`, and `version`. Loaded on every run; version is stamped
  onto each JSONL record.

### Core code

- **[models.py](promo_parser/models.py)**
  - `Verdict` — `must_see` | `maybe` | `skip`
  - `Offer` — fields extracted/scored by the model (title, merchant,
    discount, url, image_url, score, verdict, reason, …)
  - `EmailAnalysis` — wrapper `{ "offers": [...] }`; empty list = nothing
    relevant. Schema is also passed to Ollama as JSON `format` and validated
    with Pydantic after each call.
  - `Evidence` — `{ source_url, snippet }` gathered during verification.
  - `VerificationVerdict` — `is_genuine`, `authenticity_reason`,
    `quality_score` (0-1), `quality_reason`, `evidence`, `recommend`.
  - `VerifiedOffer` — `{ offer, verification, passed }`; the verified JSONL row.

- **[gmail/client.py](promo_parser/gmail/client.py)**
  - `get_service()` — OAuth flow; refreshes or opens browser; caches
    `token.json`.
  - `list_message_ids()` — paginated list for `GMAIL_QUERY`.
  - `fetch_email()` — returns `Email` dataclass: `message_id`, `thread_id`,
    `sender`, `subject`, `received_at`, `snippet`, `body`.
  - Body extraction prefers `text/plain`; falls back to HTML stripped via
    BeautifulSoup.

- **[analyze/analyzer.py](promo_parser/analyze/analyzer.py)**
  - `load_profile()` — reads YAML profile.
  - `analyze_email()` — single-shot Ollama call with structured output;
    one automatic retry if JSON fails validation; raises `AnalysisError` on
    second failure (email is **not** marked seen in `run.py`).

- **[storage/storage.py](promo_parser/storage/storage.py)**
  - `load_seen_ids()` / `save_seen_ids()` — JSON array of Gmail message IDs.
  - `append_offers()` — one JSONL line per offer, enriched with
    `message_id`, `sender`, `subject`, `received_at`, `profile_version`,
    `model`, `created_at`.
  - `latest_results_file()` / `load_offers()` — find and read a results JSONL.
  - `append_verified()` / `verified_path_for_today()` — write verified rows.

- **[cli/run.py](promo_parser/cli/run.py)** (wrapper: [scripts/run.py](scripts/run.py))
  - Flags: `--limit N` (cap new emails), `--dry-run` (no writes, no seen
    marks), `-v`/`--verbose` (DEBUG logging).
  - Calls `setup_logging()` first; all progress goes through `logging`.
  - Pre-filter: skip seen IDs; skip empty body+snippet (still marks seen).
  - Prints per-email status and a final summary (fetched / analyzed / offers /
    errors).

### Part 2 — verification

- **[verify/search.py](promo_parser/verify/search.py)**
  - `SearchClient` — wraps a web search provider (default Tavily); key from
    `.env`. `find_price_info(product)` and `find_reviews(product)` return
    `[{title, url, snippet}]`. Only product title/merchant is sent out.

- **[verify/verifier.py](promo_parser/verify/verifier.py)** (the `manual` engine)
  - `verify_offer(client, search, offer, profile)` — bounded agentic loop. The
    model has three tools: `find_price_info`, `find_reviews`, and
    `submit_verdict`. It keeps calling the search tools until it has enough
    evidence, then calls `submit_verdict` (an explicit control signal,
    `DECIDE_TOOL`) to end the loop; a turn with no tool calls also ends it, and
    `MAX_VERIFY_ITERS` is the safety ceiling. A final `format`-constrained call
    then extracts a `VerificationVerdict`. Raises `VerificationError` on failure.
  - Exposes `SYSTEM_PROMPT`, `_build_user_prompt`, and `VerificationError`,
    which the Agno engine reuses.

- **[verify_agno/verifier.py](promo_parser/verify_agno/verifier.py)** (the `agno` engine, optional)
  - `verify_offer(offer, profile, *, search, host)` — same contract, but an
    Agno `Agent` runs the tool loop and the structured extraction
    (`output_schema=VerificationVerdict`), replacing the manual `for`-loop and
    `_extract_verdict()`. Reuses the manual engine's `SYSTEM_PROMPT`,
    `_build_user_prompt`, `VerificationError`, plus `VerificationVerdict` and
    `SearchClient`. Two tools only (no `submit_verdict`; Agno stops on the final
    non-tool response). `agno` is imported lazily; missing it raises a
    `VerificationError` pointing at `requirements-agno.txt`. `tool_call_limit`
    is a soft bound, and non-schema output is rejected with `VerificationError`.

- **[cli/verify.py](promo_parser/cli/verify.py)** (wrapper: [scripts/verify.py](scripts/verify.py))
  - Flags: `--input PATH` (default latest run), `--limit N`, `--dry-run`,
    `--engine {manual,agno}` (default `config.VERIFY_ENGINE`),
    `-v`/`--verbose` (DEBUG logging).
  - Picks the engine and wraps it in a uniform per-offer callable, so the loop,
    logging, and summary are engine-agnostic.
  - Gate: only offers with verdict `must_see`/`maybe` are verified.
  - `passed = is_genuine and quality_score >= QUALITY_THRESHOLD`.
  - Logs per-offer PASS/fail (with evidence count + timing) and a final summary.

### Dependencies

- **[requirements.txt](requirements.txt)** — `google-api-python-client`,
  `google-auth-oauthlib`, `ollama`, `pydantic`, `PyYAML`, `beautifulsoup4`,
  `tavily-python`, `python-dotenv`.
- **[requirements-agno.txt](requirements-agno.txt)** — optional `agno`, only
  needed for `--engine agno`. Install with
  `pip install -r requirements.txt -r requirements-agno.txt`.

## JSONL record shape

Each line in `results/run_YYYY-MM-DD.jsonl` is one offer plus provenance.
Field names match the future SQLite `offers` table (Part 2).

| Field | Source |
|---|---|
| `title`, `merchant`, `category`, `discount_*`, `price_*`, `expires_at`, `url`, `image_url`, `score`, `verdict`, `reason` | LLM (`Offer`) |
| `message_id`, `sender`, `subject`, `received_at` | Gmail (`Email`) |
| `profile_version` | `interest_profile.yaml` |
| `model` | `config.OLLAMA_MODEL` |
| `created_at` | UTC timestamp at write time |

### verified JSONL record shape

Each line in `results/verified_YYYY-MM-DD.jsonl` carries the original offer
fields plus:

| Field | Source |
|---|---|
| `verification.is_genuine`, `authenticity_reason`, `quality_score`, `quality_reason`, `evidence`, `recommend` | Verifier model + search |
| `passed` | `is_genuine and quality_score >= QUALITY_THRESHOLD` |
| `verifier_model`, `verified_at` | Provenance |

Get just the survivors: `jq 'select(.passed)' results/verified_*.jsonl`.

## External services

| Service | Used for | Config |
|---|---|---|
| Gmail API | Read Promotions (readonly) | `credentials.json`, `token.json`, `GMAIL_QUERY` |
| Ollama (local) | Classify offers (Part 1) + verify deals (Part 2) | `OLLAMA_HOST`, `OLLAMA_MODEL`, `VERIFIER_MODEL` |
| Tavily (web search) | Price/review evidence for verification | `TAVILY_API_KEY` |

No cloud LLM, database, or scheduler yet.

## What is not in this repo yet (planned later)

- HTML report rendering and email/file delivery
- Claude intro via LiteLLM
- SQLite storage and weekly `launchd` scheduling
- Idempotency/caching for the verification stage

See the architecture diagrams in `*.drawio` if present — they describe the
full system; this codebase implements **Part 1 and Part 2**.

## Related docs

- Setup: [GETTING_STARTED.md](GETTING_STARTED.md)
- Pipeline & model: [HOW_IT_WORKS.md](HOW_IT_WORKS.md)
- Quick run: [README.md](README.md)
