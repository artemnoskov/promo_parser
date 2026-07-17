 # Getting Started

A step-by-step walkthrough for setting up and running the promo parser for
the first time. For a short overview of the project, see [README.md](README.md).

## What you'll end up with

After a successful run:

- `results/run_YYYY-MM-DD.jsonl` — one JSON line per offer the model found
  relevant to your profile.
- `seen_ids.json` — the message IDs already processed (makes re-runs
  idempotent).
- `token.json` — your cached Gmail OAuth token (read-only scope).

## Step 1 — Google Cloud OAuth client (one-time, ~10 minutes)

This is the most fiddly step. You need a `credentials.json` file that lets
the script ask *you* for read-only access to *your own* Gmail.

1. Go to <https://console.cloud.google.com/> and create a new project
   (any name, e.g. `promo-parser`).
2. **Enable the Gmail API**: menu → *APIs & Services* → *Library* → search
   "Gmail API" → *Enable*.
3. **Configure the OAuth consent screen**: *APIs & Services* → *OAuth
   consent screen*:
   - User type: **External**.
   - Fill in only the required fields (app name, your email).
   - You do not need to submit for verification — instead add your own
     Gmail address under **Test users**. Test mode is fine forever for a
     personal tool.
4. **Create the client**: *APIs & Services* → *Credentials* → *Create
   Credentials* → *OAuth client ID* → Application type: **Desktop app**.
5. Download the JSON and save it as `credentials.json` **in this project
   directory** (it is gitignored).

Notes:

- The script only requests the `gmail.readonly` scope — it can never send,
  modify, or delete mail.
- In test mode, Google expires the token after 7 days; when that happens
  just delete `token.json` and re-consent on the next run.

## Step 2 — Ollama + Qwen (one-time)

1. Install Ollama: <https://ollama.com/download> (or `brew install ollama`).
2. Start it (the desktop app runs it automatically, or run `brew services start ollama`).
3. **Check the version** — Qwen 3.6 needs Ollama **0.17+** (0.31+ recommended):

   ```bash
   ollama --version
   ```

   If you're on an old Homebrew install (e.g. 0.14.x), upgrade:

   ```bash
   brew upgrade ollama
   brew services restart ollama
   ```

4. Pull the model:

   ```bash
   ollama pull qwen3.6:35b-a3b
   ```

5. Check the exact tag and make sure `OLLAMA_MODEL` in [config.py](config.py)
   matches it:

   ```bash
   ollama list
   ```

Any Qwen (or other instruct) model works as long as the tag in `config.py`
matches something in `ollama list`.

## Step 3 — Python environment (one-time)

From the project directory:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

(If a `.venv/` already exists from an earlier setup, just activate it.)

## Step 4 — First run

Start small and safe — analyze 5 emails without writing anything:

```bash
python run.py --limit 5 --dry-run
```

What happens on the first run:

1. A browser window opens asking you to sign in to Google and approve
   read-only Gmail access. You'll see an "unverified app" warning because
   the app is in test mode — click *Continue*. The token is cached in
   `token.json`, so this happens only once.
2. The script lists last week's Promotions, sends each new email to Qwen,
   and prints a line per email with the offer count and best verdict/score.
3. A run summary prints at the end (fetched / analyzed / offers / errors).

If that looks sane, do a real run:

```bash
python run.py
```

## Step 5 — Verify

Inspect the results:

```bash
jq . results/run_*.jsonl                                    # everything
jq 'select(.verdict == "must_see")' results/run_*.jsonl     # the good stuff
jq -s 'sort_by(-.score) | .[] | {title, merchant, discount_text, score}' results/run_*.jsonl
```

Confirm idempotency — run it again immediately:

```bash
python run.py
```

The summary should show everything as already seen and analyze nothing new.

## Step 6 — Tune your profile

Edit [interest_profile.yaml](interest_profile.yaml) — the starter values are
placeholders. Set your real interests, brands, never-interested list, and
price rules, and bump `version` whenever you change it (each offer records
which profile version scored it). Then re-run and compare verdicts.

## Troubleshooting

| Symptom | Fix |
|---|---|
| `Missing credentials.json` on start | Complete Step 1 and put the file in the project root. |
| Browser consent screen shows "app not verified" | Expected in test mode — click *Continue* (you added yourself as a test user). |
| `invalid_grant` / auth errors after ~7 days | Test-mode tokens expire. Delete `token.json` and re-run to re-consent. |
| Connection refused to `localhost:11434` | Ollama isn't running — start the app or `brew services start ollama`. |
| `unable to load model` (500) for `qwen3.6:35b-a3b` | Ollama is too old for the `qwen35moe` architecture. Upgrade and restart: `brew upgrade ollama && brew services restart ollama`. Confirm with `ollama --version` (need 0.17+; 0.31+ recommended). Temporary fallback: set `OLLAMA_MODEL = "qwen2.5:7b"` in `config.py`. |
| `model not found` from Ollama | The tag in `config.py` doesn't match `ollama list`. Pull the model or fix `OLLAMA_MODEL`. |
| Model returns invalid JSON twice (`ERROR` lines) | Occasional with local models; those emails are *not* marked seen and retry next run. Frequent failures usually mean the model tag points at a non-instruct model. |
| Run is slow | Normal for a first pass on a big week. Use `--limit` while testing; the full weekly batch is meant to run unattended. |
| Want to reprocess everything from scratch | Delete `seen_ids.json` (and optionally `results/`). |

## Day-to-day usage

```bash
source .venv/bin/activate
python run.py                 # weekly manual run
python run.py --limit 10      # quick test after tweaking the profile
python run.py --dry-run       # experiment without writing state
```

That's the whole MVP loop: run, inspect the JSONL, tweak
`interest_profile.yaml`, repeat.

For a detailed breakdown of each pipeline step and how the model/prompts work,
see [HOW_IT_WORKS.md](HOW_IT_WORKS.md).
