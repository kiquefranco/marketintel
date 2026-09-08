# Onboarding: Healthcare Market Intelligence Platform

Welcome. This gets you from zero to a working local copy of the daily briefing pipeline in
about 20 minutes. Follow the steps in order.

**What this project does:** it pulls healthcare news each weekday morning, scores every story
by relevance to UHealth with an LLM, removes duplicates, writes a short narrative for the top
stories, and emails an HTML digest to executives. `README.md` explains the *why* behind each
step; `CLAUDE.md` is the fast catch-up doc on the current design. Read both once you're running.

> **Read this before you run anything:** a bare `python run_briefing.py` sends a **real email to
> real executives** and spends real money on API calls. Every command in this guide is a safe
> one. Don't run the real send until someone on the team walks you through it.

---

## Before you start — ask the team for

1. A **GitHub collaborator invite** to `kiquefranco/marketintel` (the repo is private).
2. **API keys** for your own local use — Gemini at minimum. Ask how the team is issuing these;
   do not copy someone else's `.env` file over Slack or email.
3. Read access to `docs/Implementation_Plan.docx` for background.

You do **not** need keys for Step 5, the first run. That one is free and offline-ish by design.

---

## Step 1 — Install the prerequisites

You need **Python 3.10 or newer** and **git**. Check what you have:

```bash
python3 --version
git --version
```

On a Mac, if either is missing:

```bash
brew install python git
```

Optional but recommended — the GitHub CLI, which handles auth for you so you never have to
paste a token anywhere:

```bash
brew install gh
gh auth login          # choose GitHub.com -> HTTPS -> login with a browser
```

---

## Step 2 — Clone the repository

Pick a folder you'll remember, then:

```bash
cd ~/Projects                                  # or wherever you keep code
gh repo clone kiquefranco/marketintel       # if you installed gh (easiest)
# or, if you already have an SSH key on your GitHub account:
git clone git@github.com:kiquefranco/marketintel.git

cd marketintel
```

Use the **GitHub CLI** or **SSH** option from the green *Code* button on the repo page. Avoid
the plain HTTPS URL: GitHub no longer accepts account passwords over HTTPS, so people end up
pasting an access token into the URL to make it work.

**Never put a password or access token into the clone URL.** Use `gh auth login` or an SSH key.
A token pasted into a URL gets saved in plain text in `.git/config` and leaks to anyone who can
read your disk or your screen.

Sanity check that you're in the right place:

```bash
ls
# you should see: run_briefing.py  requirements.txt  config/  src/  scripts/  docs/
```

> **Do this step yourself, in your own Terminal.** Claude can help with everything after the
> clone, but not with the clone itself — see the note below.

### A note on using Claude with this project

Where you run Claude changes what it can do:

- **Claude Code in your own terminal** (`claude` on your Mac) has your network and your
  installed tools. It can clone, install packages, and run everything in this guide.
- **Claude in Cowork / a sandboxed session** works on your files through a restricted
  environment: **GitHub and package registries are blocked, and `gh` isn't installed.** Clone
  and `pip install` will fail there with a proxy or network error. That's expected — it's the
  sandbox, not a broken setup.

So: **do Steps 1–3 yourself in Terminal.** After that, either kind of session can read the code,
explain the pipeline, edit config, and run the offline commands. Once the repo is on your disk:

> Read `README.md` and `CLAUDE.md` in this repo and give me an orientation: what the pipeline
> does at each stage, which files I'd touch to change how stories are scored, and what I should
> be careful not to break.

Anywhere below where a step says "with Claude", you can paste the quoted prompt as-is.

---

## Step 3 — Create a virtual environment and install dependencies

A virtual environment keeps this project's packages separate from everything else on your
machine. From inside the `marketintel` folder:

```bash
python3 -m venv .venv
source .venv/bin/activate           # Windows: .venv\Scripts\activate
pip install --upgrade pip
pip install -r requirements.txt
```

Your shell prompt should now start with `(.venv)`. That's how you know the environment is
active.

**You must re-run `source .venv/bin/activate` every time you open a new terminal.** If a command
below fails with `ModuleNotFoundError`, that's almost always what you forgot.

Confirm it worked:

```bash
python -c "import feedparser, yaml, numpy; print('dependencies OK')"
```

---

## Step 4 — Set up your `.env` file

Secrets live in a `.env` file in the project root. It is **gitignored and must stay that way** —
it never gets committed, ever.

Start from the template:

```bash
cp .env.example .env
```

Now open `.env` and fill in what you have. Here's what each variable is for:

| Variable | What it's for | Needed to get started? |
|---|---|---|
| `GEMINI_API_KEY` | The LLM that scores and writes stories. This is the default provider. | **Yes**, for Step 6 onward |
| `ANTHROPIC_API_KEY` | Alternative LLM, only if `config/settings.yaml` has `llm.provider: anthropic` | No |
| `YUTORI_API_KEY` | Agents that monitor competitor newsrooms with no RSS feed | No — use `--no-yutori` |
| `SMTP_HOST` / `SMTP_PORT` | Mail server. `smtp.gmail.com` / `587` for Gmail. | Only for real sends |
| `SMTP_USER` / `SMTP_PASS` | Gmail address and an **App Password** (not your account password) | Only for real sends |
| `EMAIL_FROM` | Sender address shown on the digest | Only for real sends |
| `EMAIL_TO` | Fallback recipient list | Only for real sends |
| `ALERT_EMAIL_TO` | Where the watchdog sends failure alerts | No |

Three things that trip people up:

- **Gmail needs an App Password**, not your normal password. Google Account → Security →
  2-Step Verification → App passwords.
- **The real digest recipients are not in `.env`.** They're in
  `config/settings.yaml` under `briefing.digest_recipients`. Changing `EMAIL_TO` does not change
  who gets the executive briefing. Know this before you touch anything email-related.
- **Leave a key blank rather than guessing.** A wrong key produces confusing errors; a blank one
  produces a clear "missing key" error.

Verify your `.env` is invisible to git — this should print nothing at all:

```bash
git status --porcelain | grep '\.env$'
```

### Doing this with Claude

> Read `.env.example` and `config/settings.yaml` in this repo and tell me exactly which
> environment variables I need to run `run_briefing.py --dry-run --no-yutori`, and which ones I
> can leave blank. Don't print any secret values.

(This one works in either kind of session — it only reads local files.)

---

## Step 5 — Your first run (free, sends nothing)

This fetches the RSS feeds and writes to the local database, with no LLM calls and no email:

```bash
python run_briefing.py --dry-run --no-yutori --no-llm
```

- `--dry-run` — build the briefing and save it to disk, **never send email**
- `--no-yutori` — skip the paid competitor-scout agents
- `--no-llm` — skip all LLM scoring and synthesis (so this costs nothing and needs no keys)

If that finishes without a traceback, your environment is correct. Congratulations, you're set up.

You can also check the feed list is healthy:

```bash
python scripts/verify_sources.py
```

Some feeds being quiet is a known, tracked issue — not something you broke.

---

## Step 6 — A full dry run (uses your Gemini key, still sends nothing)

Once you have `GEMINI_API_KEY` in `.env`:

```bash
python run_briefing.py --dry-run --no-yutori
```

This does the real thing — scores every story, dedupes, writes narratives — and saves the
rendered HTML to `data/briefings/` instead of emailing it. Open the newest file in that folder
in your browser to see exactly what the executives would receive.

Then, to understand *why* each story ranked where it did:

```bash
python scripts/score_report.py
```

This is the single most useful command on the project. The scoring rubric itself lives in
`config/settings.yaml` under `briefing.relevance_guidance` — that block is the brain of the
whole system, and `PRIORITIZATION_CHANGELOG.md` records why it says what it says.

Costs a few cents per run. Keep `--no-yutori` on unless you have a reason not to: the scout
agents are ~80% of the project's monthly bill.

### Doing this with Claude

> Run `python run_briefing.py --dry-run --no-yutori`, then `python scripts/score_report.py`, and
> walk me through why the top three stories scored the way they did against the rubric in
> `config/settings.yaml`.

---

## Step 7 — Run the tests

Several checks run offline with no network or database access:

```bash
python scripts/test_reconcile.py
python scripts/test_dedup_measures.py
python scripts/test_profile_scoring.py
```

Run these before you open a pull request.

---

## Working on the project day to day

**Every new terminal:**

```bash
cd path/to/marketintel && source .venv/bin/activate
```

**The one git quirk you need to know.** The CI bot commits `data/intel.db` back to the repo
after every successful run — that file is the pipeline's durable memory of what's already been
briefed. This means the remote branch moves ahead on its own, and your local copy of that file
will conflict. Before you pull or push:

```bash
git checkout -- data/intel.db && git pull --no-rebase
```

Don't fight the conflict; just discard your local copy of the database as shown.

**Where things live:**

| Path | What's in it |
|---|---|
| `run_briefing.py` | The orchestrator — ingest → prioritize → synthesize → send |
| `config/settings.yaml` | Scoring rubric, thresholds, recipients. Most tuning happens here. |
| `config/sources.yaml` | Which feeds and competitor scouts are monitored |
| `src/ingest/` | Fetching and date-enriching articles |
| `src/prioritize/` | LLM scoring and semantic dedup |
| `src/output/` | Narrative synthesis and HTML email rendering |
| `scripts/` | One-off tools, diagnostics, and tests |
| `docs/SCORING.md`, `docs/PROFILES.md` | Deeper dives on how scoring works |

**Ground rules:**

- Never commit `.env`, API keys, or tokens. Check `git diff --staged` before every commit.
- Never run `python run_briefing.py` without `--dry-run` unless you intend to email executives.
- Adding a competitor scout costs about $10.64/month against a $100 budget. Re-run the numbers
  in `README.md` before adding one.
- The pipeline reads internal UHealth context to inform scoring only. Internal plans, figures,
  and named people must never appear in anything that gets sent out.

---

## When something breaks

| Symptom | Cause |
|---|---|
| `ModuleNotFoundError` | The virtual environment isn't active — run `source .venv/bin/activate` |
| `403 from proxy` / network errors on clone or `pip install` | You're in a sandboxed Claude session, which has no GitHub or PyPI access. Run those commands in your own Terminal instead. |
| "missing key" / auth error | A blank or wrong value in `.env` |
| An LLM "region not available" error | Usually exhausted API billing credits, not an actual region block — check billing first |
| Git conflict on `data/intel.db` | Expected. `git checkout -- data/intel.db && git pull --no-rebase` |
| No stories in the briefing | Possibly a genuine quiet day; check `python scripts/score_report.py` before assuming a bug |

Stuck for more than 20 minutes? Ask. Someone has almost certainly hit it before.
