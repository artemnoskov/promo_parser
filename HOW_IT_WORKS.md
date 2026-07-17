# How It Works — Step by Step

What happens when you run the promo parser, and how the local LLM is used.
For setup instructions see [GETTING_STARTED.md](GETTING_STARTED.md). For file
layout see [PROJECT_STRUCTURE.md](PROJECT_STRUCTURE.md).

---

## Part A — What happens when you run `python run.py`

Each step maps to code in [run.py](run.py) and related modules.

### Step 1 — Load configuration

- Read [config.py](config.py): Gmail query, model name (`OLLAMA_MODEL`), paths.
- Read [interest_profile.yaml](interest_profile.yaml) via `analyzer.load_profile()`.
- Load `seen_ids.json` (if it exists) into a set of already-processed message IDs.

### Step 2 — Check Ollama

- [ollama_check.py](ollama_check.py) pings `http://localhost:11434`.
- Sends a tiny test message to confirm the configured model **loads** (not just
  listed). Fails fast with a clear error if Ollama is down or the model is
  broken.

### Step 3 — Authenticate with Gmail

- [gmail_client.py](gmail_client.py) loads or refreshes `token.json`.
- If missing/expired and no refresh token: opens a browser for OAuth consent
  (scope: `gmail.readonly` only).

### Step 4 — List Promotions emails

- Gmail API query (from config): `category:promotions newer_than:7d`.
- Returns up to 200 message IDs (paginated).

### Step 5 — Pre-filter (per message)

For each message ID:

1. **Skip if seen** — ID is in `seen_ids.json` → do nothing (idempotent).
2. **Fetch full email** — headers + body (plain text preferred, HTML stripped as fallback).
3. **Skip if empty** — no body and no snippet → mark seen, continue.

### Step 6 — Analyze with the local model

- Call `analyzer.analyze_email()` — see **Part B** below.
- On success: get an `EmailAnalysis` object with zero or more `Offer`s.
- On failure (`AnalysisError`): log error, **do not** mark seen (retries next run).

### Step 7 — Store results

Unless `--dry-run`:

- For each offer: append one JSON line to `results/run_YYYY-MM-DD.jsonl`
  ([storage.py](storage.py)).
- Add message ID to `seen_ids.json`.

### Step 8 — Print summary

Example:

```
Run summary: 92 fetched | 5 analyzed | 3 offers | 0 errors | 0 empty-skipped
```

---

## Part B — What happens for one email (the model call)

All prompt and LLM logic lives in [analyzer.py](analyzer.py). Output shape is
defined in [models.py](models.py).

There is **no agentic loop** in this MVP: one chat request per email (plus at
most one retry if JSON validation fails).

### Step B1 — Build the messages

Two chat messages are sent to Ollama:

| Role | Source | Purpose |
|---|---|---|
| `system` | `SYSTEM_PROMPT` constant in `analyzer.py` | Fixed rules: judge promos, return JSON only, don't invent data |
| `user` | `_build_user_prompt()` | Your profile YAML + email sender/subject/date/body |

**System prompt** (abbreviated — full text in `analyzer.py`):

```
You judge promotional emails against a user's interest profile.
Return ONLY a JSON object matching the provided schema: {"offers": [...]}.
...
Apply the profile's price rules and never_interested_in list strictly.
If nothing relevant, return {"offers": []}.
Do not invent offers, prices or dates that are not in the email.
```

**User prompt** is built like this:

```
USER PROFILE:
<contents of interest_profile.yaml>

EMAIL:
From: deals@merchant.com
Subject: 50% off sale
Date: Fri, 10 Jul 2026 ...

<email body, truncated to MAX_BODY_CHARS (8000) from config.py>
```

The profile file carries **your** interests, brands, price rules, and scoring
rubric. The system prompt tells the model **how** to use that profile.

### Step B2 — Attach the output schema

- `EmailAnalysis.model_json_schema()` from [models.py](models.py) is passed to
  Ollama as `format=schema`.
- Ollama constrains generation toward JSON matching that schema.
- Expected shape:

```json
{
  "offers": [
    {
      "title": "50% off TKL keycaps",
      "merchant": "KBDfans",
      "score": 0.92,
      "verdict": "must_see",
      "reason": "Big discount on a stated interest",
      "discount_text": "50% off",
      "url": null,
      "image_url": null
    }
  ]
}
```

`verdict` must be one of: `must_see`, `maybe`, `skip`.  
`score` must be between 0.0 and 1.0.

### Step B3 — Call Ollama

```python
client.chat(
    model=config.OLLAMA_MODEL,      # e.g. "qwen2.5:7b"
    messages=[system, user],
    format=schema,                   # JSON schema from Pydantic
    options={"temperature": 0.1},   # low randomness
)
```

- Model runs **locally** via Ollama at `OLLAMA_HOST` (default `localhost:11434`).
- No cloud API, no tools, no multi-turn conversation (except retry).

### Step B4 — Validate with Pydantic

- Parse the model's reply string with `EmailAnalysis.model_validate_json()`.
- If valid → return the object to `run.py`.

### Step B5 — Retry once on bad JSON (optional second call)

If validation fails:

1. Append the model's bad reply to the conversation.
2. Append a corrective user message (`RETRY_NUDGE`): "Respond again with ONLY
   the JSON object, no prose."
3. Call Ollama again (same schema, same temperature).

If the second attempt also fails → raise `AnalysisError` → email not marked seen.

---

## Part C — Where to edit what

| You want to change… | Edit this |
|---|---|
| Interests, brands, price thresholds, scoring rubric | [interest_profile.yaml](interest_profile.yaml) |
| How the model judges (rules, tone, anti-hallucination) | `SYSTEM_PROMPT` in [analyzer.py](analyzer.py) |
| Fields the model must return (add/remove columns) | `Offer` in [models.py](models.py) |
| Which local model runs | `OLLAMA_MODEL` in [config.py](config.py) |
| How much email text the model sees | `MAX_BODY_CHARS` in [config.py](config.py) |
| Gmail search window / category | `GMAIL_QUERY` in [config.py](config.py) |

After changing `interest_profile.yaml`, bump its `version` field — each JSONL
record stores `profile_version` so you can tell which profile produced a score.

---

## Part D — End-to-end diagram

```
python run.py
    │
    ├─ load config + profile + seen_ids
    ├─ check Ollama (model loads?)
    ├─ Gmail OAuth → list Promotions (7d)
    │
    └─ for each message (not in seen_ids):
           │
           ├─ fetch email body
           │
           ├─ analyzer.analyze_email()
           │      system: SYSTEM_PROMPT (analyzer.py)
           │      user:   profile.yaml + email text
           │      format: EmailAnalysis JSON schema (models.py)
           │      → Ollama (local) → validate → maybe retry once
           │
           ├─ append offers → results/run_YYYY-MM-DD.jsonl
           └─ mark message_id → seen_ids.json
```

---

## Part E — Verification stage (Part 2, `verify.py`)

Part 1 decides *is this relevant to me?* Part 2 adds a second, optional pass that
asks *is this deal real, and is the product good?* — using an agentic loop where a
local reasoning model calls web-search tools for evidence.

It is a **separate script** that reads Part 1's output, so you can iterate on it
without re-fetching Gmail.

### Step by step

1. **Load offers** — read the latest `results/run_*.jsonl` (or `--input PATH`).
2. **Preflight** — confirm `VERIFIER_MODEL` (`qwen3.6:35b-a3b`) loads in Ollama
   and the search provider (Tavily) has a key.
3. **Gate** — only offers with verdict `must_see` or `maybe` are verified;
   `skip` offers are ignored. Junk/empty email URLs no longer matter because
   evidence comes from web search, not the email link.
4. **Agentic loop per offer** ([verifier.py](verifier.py)) — bounded by
   `MAX_VERIFY_ITERS`:
   - The model is given two tools: `find_price_info` and `find_reviews`.
   - Each turn it either **calls a tool** (we run the search, append results to
     the conversation, loop) or **stops**.
   - When it stops (or the cap is hit), a final `format`-constrained call
     extracts a `VerificationVerdict`.
5. **Decide** — `passed = is_genuine and quality_score >= QUALITY_THRESHOLD`.
6. **Store** — append every evaluated offer (plus verdict + `passed`) to
   `results/verified_YYYY-MM-DD.jsonl`.

### The verdict schema (`models.VerificationVerdict`)

```json
{
  "is_genuine": true,
  "authenticity_reason": "Street price ~$2200; $1799 is a real discount",
  "quality_score": 0.85,
  "quality_reason": "Consistently rated 4.5+ across reviews",
  "evidence": [{"source_url": "https://...", "snippet": "..."}],
  "recommend": true
}
```

### Why a separate reasoning model?

`VERIFIER_MODEL` is `qwen3.6:35b-a3b` (a real reasoning model with tool-calling),
kept distinct from the Part 1 `OLLAMA_MODEL`. Verification is a harder judgment
task and benefits from the stronger model; classification can stay on whatever
you prefer.

### Run it

```bash
python verify.py --input results/run_2026-07-12.jsonl --limit 3   # test
python verify.py                                                   # latest run
jq 'select(.passed)' results/verified_*.jsonl                      # survivors
```

Requires `TAVILY_API_KEY` in `.env` (see `.env.example`).

### Part 2 diagram

```
python verify.py
    │
    ├─ load offers ← results/run_*.jsonl
    ├─ check Ollama (VERIFIER_MODEL) + search key
    │
    └─ for each offer (verdict must_see/maybe):
           │
           └─ verifier.verify_offer()
                  loop (max MAX_VERIFY_ITERS):
                    Ollama chat + tools
                    ├─ tool call? → find_price_info / find_reviews → append evidence → repeat
                    └─ no tool?   → break
                  final format-constrained call → VerificationVerdict
           │
           ├─ passed = is_genuine and quality_score >= QUALITY_THRESHOLD
           └─ append → results/verified_YYYY-MM-DD.jsonl
```

---

## Part F — What this still does *not* do

- **No report rendering** — output is JSONL only (HTML/email is later work).
- **No scheduling** — you run `run.py` / `verify.py` manually (later: `launchd`).
- **No SQLite** — results are flat files; a DB can be added without changing
  the field shapes.
- **No verification caching** — re-running `verify.py` re-verifies offers.

---

## Related docs

- [GETTING_STARTED.md](GETTING_STARTED.md) — install, OAuth, first run, troubleshooting
- [PROJECT_STRUCTURE.md](PROJECT_STRUCTURE.md) — every file and module
- [README.md](README.md) — quick reference
