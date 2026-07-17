# Project Structure

Overview of the **promo_parser** repository: what each file does, how modules
connect, and what gets created at runtime.

Two stages exist today:

- **Part 1** — inbox to JSONL (`run.py`): fetch, classify, store offers.
- **Part 2** — deal verification (`verify.py`): an agentic loop that checks
  whether promising offers are genuine and good, using a local reasoning model
  plus web search.

No database, no report rendering, no scheduling yet.

## Directory tree

```
promo_parser/
├── README.md                 # Project overview and quick reference
├── GETTING_STARTED.md        # First-time setup and troubleshooting
├── HOW_IT_WORKS.md           # Step-by-step pipeline and model/prompt flow
├── PROJECT_STRUCTURE.md      # This file
├── requirements.txt          # Python dependencies
├── .gitignore
│
├── config.py                 # Paths and constants (Gmail, Ollama, storage)
├── interest_profile.yaml     # Your interests, brands, scoring rules (editable)
│
├── models.py                 # Pydantic schemas the LLM must return
├── ollama_check.py           # Preflight: Ollama up + model loads
├── gmail_client.py           # Gmail OAuth + fetch/parse emails
├── analyzer.py               # Prompt, Ollama call, validation + retry
├── storage.py                # seen_ids.json + results/*.jsonl
├── run.py                    # Part 1 CLI (fetch → classify → store)
│
├── search_client.py          # Web search wrapper (price/reviews evidence)
├── verifier.py               # Part 2 agentic verification loop (tools + model)
├── verify.py                 # Part 2 CLI (gate → verify → verified JSONL)
└── .env.example              # Template for TAVILY_API_KEY
```

### Created at runtime (gitignored)

These files appear after you run the project. They are not committed to git.

```
promo_parser/
├── credentials.json               # You download this from Google Cloud (one-time)
├── token.json                     # Cached Gmail OAuth token after first consent
├── .env                           # TAVILY_API_KEY for the verification stage
├── seen_ids.json                  # Message IDs already processed (idempotency)
├── results/
│   ├── run_YYYY-MM-DD.jsonl       # Part 1: one JSON object per offer
│   └── verified_YYYY-MM-DD.jsonl  # Part 2: offer + verification + passed
└── .venv/                         # Local Python virtual environment (optional)
```

## Module map

| Module | Role |
|---|---|
| [run.py](run.py) | Part 1 CLI: wires fetch → filter → analyze → store; prints run summary |
| [ollama_check.py](ollama_check.py) | Preflight: verify Ollama is up and a given model loads |
| [gmail_client.py](gmail_client.py) | OAuth, list/fetch Promotions, extract plaintext body |
| [analyzer.py](analyzer.py) | Build prompt from profile + email; call Ollama; validate JSON |
| [storage.py](storage.py) | Load/save `seen_ids.json`; append offers + verified rows to JSONL |
| [models.py](models.py) | `Offer`, `Verdict`, `EmailAnalysis`, `VerificationVerdict`, `VerifiedOffer` |
| [config.py](config.py) | Single place for paths, model names, Gmail query, limits, verification settings |
| [search_client.py](search_client.py) | Part 2: web search wrapper (`find_price_info` / `find_reviews`) |
| [verifier.py](verifier.py) | Part 2: bounded agentic loop (tool-calling + structured verdict) |
| [verify.py](verify.py) | Part 2 CLI: gate offers → verify → write verified JSONL |

## Data flow

```
run.py
  │
  ├─► gmail_client.get_service()     OAuth → Gmail API service
  ├─► gmail_client.list_message_ids()  q: category:promotions newer_than:7d
  │
  ├─► storage.load_seen_ids()        skip already-processed messages
  │
  └─► for each new message:
        gmail_client.fetch_email()   → Email dataclass
        analyzer.analyze_email()     → EmailAnalysis (Pydantic)
          ├─ load_profile()          ← interest_profile.yaml
          └─ Ollama chat (JSON schema from models.EmailAnalysis)
        storage.append_offers()      → results/run_YYYY-MM-DD.jsonl
        storage.save_seen_ids()      → seen_ids.json
```

### Part 2 — verification (verify.py)

```
verify.py
  │
  ├─► storage.latest_results_file()  pick newest results/run_*.jsonl
  ├─► storage.load_offers()          read offers to verify
  ├─► ollama_check(VERIFIER_MODEL)   preflight reasoning model
  ├─► SearchClient()                 web search (needs TAVILY_API_KEY)
  │
  └─► for each offer with verdict in {must_see, maybe}:
        verifier.verify_offer()      → VerificationVerdict
          ├─ loop (max MAX_VERIFY_ITERS):
          │    Ollama chat with tools (find_price_info / find_reviews)
          │    run tool calls → append evidence → repeat
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

- **[config.py](config.py)** — Constants (loads `.env` via python-dotenv):
  - Gmail: `credentials.json`, `token.json`, readonly scope, search query,
    max emails per run (200).
  - Ollama: classifier model tag (`OLLAMA_MODEL`), host URL.
  - Verification: `VERIFIER_MODEL`, `SEARCH_PROVIDER`, `TAVILY_API_KEY`,
    `MAX_VERIFY_ITERS`, `QUALITY_THRESHOLD`, `SEARCH_MAX_RESULTS`.
  - Storage: `results/` directory, `seen_ids.json` path.
  - `MAX_BODY_CHARS` — truncates long email bodies before sending to the model.
- **[interest_profile.yaml](interest_profile.yaml)** — User-tunable input:
  `interests`, `brands_care_about`, `never_interested_in`, `price_rules`,
  `scoring_rubric`, and `version`. Loaded on every run; version is stamped
  onto each JSONL record.

### Core code

- **[models.py](models.py)**
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

- **[gmail_client.py](gmail_client.py)**
  - `get_service()` — OAuth flow; refreshes or opens browser; caches
    `token.json`.
  - `list_message_ids()` — paginated list for `GMAIL_QUERY`.
  - `fetch_email()` — returns `Email` dataclass: `message_id`, `thread_id`,
    `sender`, `subject`, `received_at`, `snippet`, `body`.
  - Body extraction prefers `text/plain`; falls back to HTML stripped via
    BeautifulSoup.

- **[analyzer.py](analyzer.py)**
  - `load_profile()` — reads YAML profile.
  - `analyze_email()` — single-shot Ollama call with structured output;
    one automatic retry if JSON fails validation; raises `AnalysisError` on
    second failure (email is **not** marked seen in `run.py`).

- **[storage.py](storage.py)**
  - `load_seen_ids()` / `save_seen_ids()` — JSON array of Gmail message IDs.
  - `append_offers()` — one JSONL line per offer, enriched with
    `message_id`, `sender`, `subject`, `received_at`, `profile_version`,
    `model`, `created_at`.
  - `latest_results_file()` / `load_offers()` — find and read a results JSONL.
  - `append_verified()` / `verified_path_for_today()` — write verified rows.

- **[run.py](run.py)**
  - Flags: `--limit N` (cap new emails), `--dry-run` (no writes, no seen
    marks).
  - Pre-filter: skip seen IDs; skip empty body+snippet (still marks seen).
  - Prints per-email status and a final summary (fetched / analyzed / offers /
    errors).

### Part 2 — verification

- **[search_client.py](search_client.py)**
  - `SearchClient` — wraps a web search provider (default Tavily); key from
    `.env`. `find_price_info(product)` and `find_reviews(product)` return
    `[{title, url, snippet}]`. Only product title/merchant is sent out.

- **[verifier.py](verifier.py)**
  - `verify_offer()` — bounded agentic loop: the model calls the two search
    tools (capped at `MAX_VERIFY_ITERS`), then a `format`-constrained call
    extracts a `VerificationVerdict`. Raises `VerificationError` on failure.

- **[verify.py](verify.py)**
  - Flags: `--input PATH` (default latest run), `--limit N`, `--dry-run`.
  - Gate: only offers with verdict `must_see`/`maybe` are verified.
  - `passed = is_genuine and quality_score >= QUALITY_THRESHOLD`.
  - Prints per-offer PASS/fail and a final summary.

### Dependencies

- **[requirements.txt](requirements.txt)** — `google-api-python-client`,
  `google-auth-oauthlib`, `ollama`, `pydantic`, `PyYAML`, `beautifulsoup4`,
  `tavily-python`, `python-dotenv`.

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
full system; this codebase implements **Part 1 only**.

## Related docs

- Setup: [GETTING_STARTED.md](GETTING_STARTED.md)
- Pipeline & model: [HOW_IT_WORKS.md](HOW_IT_WORKS.md)
- Quick run: [README.md](README.md)
