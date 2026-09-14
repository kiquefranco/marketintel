# Healthcare Market Intelligence Platform

A daily, AI-scored market-intelligence briefing for the Strategy & Transformation team at
**UHealth (University of Miami Health System)**. Every weekday morning the pipeline ingests
healthcare news across six intelligence areas, scores each story 0-10 for impact on UHealth's
strategy, removes duplicates semantically, writes a narrative for the stories that clear the
bar, and emails a personalized HTML briefing to each recipient.

Repo: `github.com/kiquefranco/marketintel` (branch `main`, private).
Companion docs: `CLAUDE.md` (architecture catch-up), `docs/SCORING.md`, `docs/PROFILES.md`,
`docs/AHP_ANALYSIS.md`, `docs/ONBOARDING.md`, `CLOUD_SCHEDULING.md`, `PRIORITIZATION_CHANGELOG.md`.

---

## 1. What actually ships each weekday

One ingestion and one house-scoring pass produce **three different emails** from **two
independent prioritizations**:

| Email | Audience | Lens | Built by |
|---|---|---|---|
| **Strategy briefing** | 6 recipients, one personalized copy each | UHealth strategy team (the house rubric) | `prioritize()` → `synthesize` → `emailer.render_digest_html` |
| **Ambulatory briefing** | 3 ambulatory leaders, one copy each | Each leader's own `role_description`, scored separately | `prioritize_for_profile()` → `_run_semantic_pass()` |
| **Prioritization comparison** | Kique + Pranav only | Diagnostic: where the two passes disagreed today | `src/output/comparison.py` |

That is 10 emails per weekday at the current roster. The comparison email carries no story
content by design; it exists to show divergence, not news.

Every email has the same two-tier shape:

* **Tier 1, full story cards.** Only stories at or above `select_threshold` (80, i.e. LLM 8.0).
  No padding. A quiet day produces a short briefing, and the length is itself a signal.
* **Tier 2, "Also worth noting".** Compact headline + source + score for the band between the
  per-area secondary floor and the tier-1 bar. Filler can never render like a top story.
* **Quiet-day note.** If nothing clears the bar, a short note still goes out (with tier 2
  attached), so silence is never mistaken for a broken pipeline.

---

## 2. Pipeline, stage by stage

```
RSS / Google-News feeds ─┐
                         ├─► SQLite  data/intel.db   (exact-URL dedup at write)
Yutori "scouts" ─────────┘        │
                                  ▼
  publish-date window: keep only items PUBLISHED in the last lookback_hours (72h)
  undated items are date-enriched first (src/ingest/enrich.py), fetch time is the
  last resort
                                  ▼
  competitor area forcing: a named South Florida competitor re-tags the story as
  south_florida_competitive BEFORE scoring, so it gets the competitive key question
                                  ▼
  per-source cap (max_per_source 15, competitor feeds exempt) → global cap (150)
                                  ▼
  LLM relevance scoring 0-10 (Gemini 2.5 Flash, temperature 0) against
  briefing.relevance_guidance. Scores saved this run are REUSED on a retry.
                                  ▼
  deterministic forced floors (config: forced_floor_rules) → composite = LLM x 10
                                  ▼
  drop below score_threshold (55) → semantic dedup (Gemini embeddings, cosine 0.82)
  same-day AND against the last dedup_history_days (60) of briefed stories
                                  ▼
  two-tier selection: tier 1 >= 80 (max 12, no padding); tier 2 per-area floors
                                  ▼
  optional Yutori deep-dive on selected stories (currently disabled)
                                  ▼
  LLM synthesis → per-story JSON → _reconcile_stories() (id matching, canonical URLs,
  duplicate/blank rejection, one retry, then drop) → broken-link flagging →
  additional_context Background note (Google Search grounding)
                                  ▼
  render + SMTP send, per profile. Files written to data/briefings/.
                                  ▼
  mark_briefed() only if a send actually succeeded (dry runs never consume dedup state)
```

Entry point: `run_briefing.py`. Every stage after scoring is fail-safe: enrichment, deep dive,
link checking and background notes can each fail without stopping the send. Scoring and
synthesis are the exceptions. If either fails the run exits non-zero, nothing is emailed,
nothing is marked briefed, and the watchdog alerts so the next trigger retries the same stories.

### Why the design is what it is

* **Publish-date window, not fetch date.** A Monday run covers back to Friday. An old story a
  scout surfaces today cannot sneak in.
* **Pure LLM relevance, no keywords.** Keyword gating was removed: it surfaced local fluff
  ("Miami" matching sports) and missed well-worded stories. Area and source weights are
  present in `weights.yaml` but set to 0.0, so composite == LLM score x 10.
* **Temperature 0.** The same article scores the same every run, so re-runs reproduce and
  saved scores are safely reusable.
* **Semantic dedup over string matching.** The same event arrives from several feeds with
  different wording. Keyword rules run as a union over the survivors as a free fallback.
* **History dedup, 60 days.** Stops an event returning under a fresh URL and publish date.
* **Re-brief is calendar-day.** A briefed story stays eligible for the rest of the same local
  day, so a same-day re-run reproduces the briefing, but a story never repeats on a later day.
  `rebrief_after_hours` in the config is the old rolling window and is no longer used.
* **No padding.** `min_stories: 0` since 2026-08-25. Before that, a thin day threw the bar away
  and shipped 5.5/10 filler that rendered identically to a real top story.

---

## 3. The two prioritizations

**House pass (strategy).** Scores every candidate against UHealth's org description and the
`briefing.relevance_guidance` rubric. This is the shared briefing.

**Semantic profile pass (ambulatory).** Re-scores the *same* already-ingested pool through one
person's `role_description` (`src/prioritize/profile_relevance.py`), landing on the same 0-10
scale so thresholds and tier bands keep their meaning. One ingestion, one house scoring pass,
two prioritizations. Cost is roughly five extra batched requests per day per profile.

`docs/PROFILES.md` documents the three profile modes:

| Mode | Trigger field | Behavior | Extra cost |
|---|---|---|---|
| name-only | neither | Identical content to the shared briefing, personal greeting only | none |
| weights (legacy) | `subscore_weights` or `ahp_pairwise` | Weighted average of the shared sub-score vector | one shared sub-scoring pass |
| semantic (preferred) | `role_description` | Article scored for relevance to that role | ~5 batched requests/day |

The weighted mode was measured and largely rejected: re-averaging a vector produced without any
knowledge of the person barely moves the ranking. Semantic scoring is a real per-person judgment.

**Confidentiality constraint.** `role_description` and `relevance_guidance` are sent to the LLM
provider on every run. Keep them to the general shape of the role: no internal plans, figures,
timelines or project names.

---

## 4. Scoring rubric

The scoring brain is a single plain-text block: `config/settings.yaml → briefing.relevance_guidance`.
Tune it with no code change. Full history in `PRIORITIZATION_CHANGELOG.md`.

**Audience is the STRATEGY team, not the C-suite.** "Important for leadership to be aware of"
is not enough. If a strategy team cannot act on it, cap it at ~6.

Three gates, applied before placing a story on the 0-10 scale:

1. **Direct UHealth relevance.** UHealth is a provider and medical school, not a drugmaker or
   insurer. A third party's fight scores 2-3.
2. **Actionability.** General market state, patient-experience awareness and routine regulatory
   color score 3-5. Opinion pieces score 1. A startup funding round scores 3-4; it matters when
   the product ships or a hospital partners.
3. **Judged against UHealth's existing position.** Relevance is a real gap, threat or
   opportunity, not a keyword match.

Vectors that can score 8-10: growth and competitive footprint in South Florida (weighted to the
expansion zones and the 35-mile PPS-exempt band), federal and state funding policy for academic
medicine, payer and reimbursement leverage, flagship service lines as a lens for external
developments, workforce and talent, adoptable AI and health-tech, integrated pharmacy, and the
partnership ecosystem.

Explicit de-prioritizations: pharmacy, drug pricing and PBM as standalone topics; UHealth's own
news; partisan political framing (policy substance still scores on its merits); rankings and
listicles; operational thought-leadership; rural and out-of-region items; cybersecurity, which
sits at 4-5 as awareness *unless* it hits a South Florida competitor, in which case it is
competitive intelligence.

Two safeguards worth knowing:

* **Name-collision verification.** Jackson (Montgomery AL), Mount Sinai (NY), Baptist (KY/TN/AL/TX),
  Memorial Hermann (Houston) and Cleveland Clinic (Ohio) all collide with local competitor names.
  Unconfirmed location scores 2-3. A story from the competitor's own newsroom scout is exempt.
* **Forced floors.** `briefing.forced_floor_rules` sets deterministic minimum scores when terms
  from every group appear in one sentence. Currently one rule: FIU + Baptist co-mention floors at 9.

The rubric is calibrated by dated worked examples drawn from real strategy-team review notes
(2026-06-17 through 2026-07-15). Add new judgments there rather than changing code.

---

## 5. Sources

`config/sources.yaml`, organized by intelligence area. `type: rss` is free; `type: yutori` is a
paid persistent scout.

| Area | Coverage |
|---|---|
| `national_policy` | CMS (Google News proxy), HHS, FDA, Healthcare Dive, Becker's, Modern Healthcare headlines, Today's Hospitalist |
| `south_florida_competitive` | Yutori scouts on Baptist, Jackson, Cleveland Clinic FL, Memorial, Mount Sinai, HCA Florida, Broward Health; UHealth's own feed; six free Google News competitor monitors; SFBJ; South Florida Hospital News |
| `payer_insurance` | KFF Health News, Fierce Healthcare (GNews proxy) |
| `innovation_ai` | STAT Health Tech, Rock Health, Healthcare IT News, Fierce Biotech, Endpoints News |
| `public_health_risk` | CDC, WHO, Florida DOH, Broward and Miami-Dade county health |
| `reputation_media` | UHealth org query plus eight local South Florida outlets, each scoped to health |

Constraints recorded in the file: do not point a Yutori scout at a paywalled site (Modern
Healthcare, Becker's) since terms prohibit it; LinkedIn has no feed and scraping violates ToS;
the CDC feed's `lastBuildDate` is stale and should be re-checked periodically.

`config/sources_candidates.yaml` holds feeds under evaluation. Verify with
`scripts/verify_candidate_feeds.py` before promoting one.

**Known ceiling.** The pool skews heavily toward local TV health news, with almost no real-estate
or construction coverage. Summaries are short, so the scorer is mostly reading headlines. Adding
sources, not tuning the scorer, is the lever that moves this.

---

## 6. Repo map

### Core

| Path | Role |
|---|---|
| `run_briefing.py` | Orchestrator (~1,300 lines): ingest, prioritize, synthesize, reconcile, render, deliver, both prioritization passes, comparison email |
| `src/config.py` | Loads `config/*.yaml` and `.env`; `config.env(key, required=)` |
| `src/llm_client.py` | Gemini/Anthropic wrapper. Gemini auth is the `x-goog-api-key` header (the `AQ.` key format does not work as `?key=`); temperature 0; 429/500/503 retry with backoff; `embed()` chunks at 100 per call |
| `src/store.py` | SQLite schema and helpers. Tables: `articles`, `source_health`, `scouts`, `profile_subscores`, `profile_scores` |
| `src/ingest/rss.py` | feedparser ingestion, strips stray HTML |
| `src/ingest/enrich.py` | Best-effort publish-date extractor (`article:published_time`, `og:`, JSON-LD, `<time>`). Never raises |
| `src/ingest/yutori.py` | Scouting API adapter; polls `/scouting/tasks/{id}/updates` past a stored cursor |
| `src/ingest/deep_dive.py` | Per-story Yutori Browsing and Research enrichment. Config-gated, currently off |
| `src/prioritize/llm_relevance.py` | Batched 0-10 scoring (batch 15). System prompt = base + rubric |
| `src/prioritize/scoring.py` | `composite()`, `semantic_dedupe_track()`, `dedupe_by_title_track()`, `forced_floor()` |
| `src/prioritize/subscores.py` | Second cheap LLM pass producing the structured strategic dimensions, versioned so stale vectors are never reused |
| `src/prioritize/profile_relevance.py` | Per-profile semantic scoring against a `role_description` |
| `src/prioritize/related_context.py` | "Is this actually new?" Background note via Google Search grounding plus prior DB coverage. Drops undated notes |
| `src/output/synthesize.py` | Briefing JSON, one story per item, echoing each item's `[n]` id |
| `src/output/emailer.py` | `render_html`, `render_digest`, `render_digest_html`, `render_quiet_html`, `send()`. Brand palette: teal `#006888` |
| `src/output/comparison.py` | Divergence-first comparison email |
| `src/profiles.py` | Profile loading, dimension weights, keyword nudges, per-profile ranking |
| `src/ahp.py` | AHP principal-eigenvector weights with consistency ratio, plus PCA-style eigen-analysis |

### Scripts

**Operations**

| Script | Purpose |
|---|---|
| `setup_scouts.py` | Create and manage Yutori scouts. `--list`, `--dry-run`, `--force`, `--sources`, `--stop`, `--restart`. Must run locally (needs `api.yutori.com`) |
| `guard_skip_if_ran.py` | Same-day duplicate suppression plus a failed-run cap. Fails open |
| `alert_capped.py` | Emails the owner when the failed-run cap halts the day |
| `watchdog.py` | Asks the GitHub API whether today's briefing succeeded; emails `[ALERT]` if not |
| `merge_intel_db.py` | Union-merge a conflicted `data/intel.db`. Use this, never pick a side |
| `send_html.py` | Send an already-rendered HTML file to one address |

**Calibration and analysis**

| Script | Purpose |
|---|---|
| `score_report.py` | Why each story ranked where it did |
| `scoring_insights.py` | Excel workbook on how the model is actually scoring; emailed on a schedule |
| `ahp.py` / `ahp_to_excel.py` | Derive defensible dimension weights from pairwise judgments; export with charts |
| `backtest_profile.py` | Re-score a historical day's pool against one profile. Never sends, never writes live columns |
| `check_profile_scoring.py` | Pre-flight against the live model for the profile path |
| `competitor_development_report.py` | Excel tracker of South Florida competitor footprint moves, deduped to one row per project |
| `personalize.py` | `--list-profiles`, `--dry-run` for the per-executive path |

**Verification and maintenance**

| Script | Purpose |
|---|---|
| `verify_sources.py` / `verify_candidate_feeds.py` | Check feed URLs (run from a real terminal, the sandbox has no network) |
| `diagnose_enrich.py` | Probe why date enrichment recovers nothing |
| `purge_stale_undated.py` | One-off cleanup of stale undated rows |
| `clean_zero_subscores.py` | Clear contaminated all-zero sub-score vectors so they re-score |
| `seed_missing_articles.py` | One-off recovery of rows lost in a DB revert |

**Tests** (no network, no DB, no send)

`test_reconcile.py`, `test_dedup_measures.py`, `test_comparison.py`, `test_profile_scoring.py`,
`test_synthesis.py` (+ `test_article.json`), `test_background_notes.py`, `test_yutori_value.py`,
`send_yutori_tests.py`.

### Config

| File | Contents |
|---|---|
| `config/settings.yaml` (~860 lines) | Org profile, key questions, the relevance rubric, synthesis style, selection thresholds, competitor terms, recipients, comparison config, forced floors, LLM models, Yutori and deep-dive settings, `additional_context` |
| `config/weights.yaml` | Composite mix, thresholds, dedup parameters, per-source caps, uncapped sources, category and source weights |
| `config/profiles.yaml` (~575 lines) | Per-person profiles: name-only, weighted, and semantic |
| `config/sources.yaml` | Feed inventory by area |
| `config/ahp.yaml` | Pairwise judgments over the nine strategic dimensions |

---

## 7. Current configuration

| Setting | Value | Meaning |
|---|---|---|
| `llm.provider` | `gemini` | Scoring and synthesis both `gemini-2.5-flash` |
| `max_tokens_synthesis` | 8000 | ~463 output tokens per story card; 4000 truncated a 12-story briefing |
| `lookback_hours` | 72 | Three days, so Monday covers the weekend |
| `score_threshold` | 55 | Basic noise floor (composite) |
| `select_threshold` | 80 | Tier-1 bar, i.e. LLM 8.0 |
| `min_stories` / `max_stories` | 0 / 12 | No padding, hard cap |
| `secondary_floor` | 70 | Tier-2 default floor |
| `secondary_floor_by_area` | competitive 60, all others 70 | A competitor item earns a glance at 6.0 |
| `secondary_max` | 6 | Tier-2 length cap |
| `dedup_cosine_similarity` | 0.82 | Lowered from 0.85 after two near-identical STAT stories both shipped |
| `dedup_history_days` | 60 | Cross-day event dedup |
| `max_per_source` | 15 | Competitor feeds exempt via `uncapped_sources` |
| `max_llm_scored_items` | 150 | Cost ceiling; most-recent kept |
| `show_consider_section` | false | "What UHealth should consider" is generated and saved but not rendered. Flip to true to restore |
| `additional_context.enabled` | true | Background note, 200-char cap, must carry an original date |
| `yutori.deep_dive.enabled` | false | See Costs |
| `composite` | source 0.0 / category 0.0 / llm 1.0 | Composite == LLM x 10 |

---

## 8. Recipients

**Two independent lists control delivery. Removing someone means changing both.**

1. `config/settings.yaml → briefing.digest_recipients`
2. `config/profiles.yaml → profiles[].active`

Current strategy roster (6): Kique (`wef28`), Jake (`jakeherman`), Pranav (`psharma`),
Aaron (`axs9248`), David (`davidreis`), Bri (`bneuburger@med.miami.edu`, note the domain).

Ambulatory roster (3, semantic profiles): Rafic Warwar (`rwarwar`), Dr. Weiss (`rew25`),
Maura Shiffman (`mshiffman`). All three share one merged `role_description` by design; only
name, display name, email and title differ. Dormant tailored `Rafic` and `Weiss` profiles are
kept inactive for a future split.

Comparison email: Kique and Pranav.

Removal convention: set `active: false` and leave the email in place with a dated comment so the
profile can be restored (Fernando 2026-08-17, CJ 2026-09-04).

`briefing.recipient_lists` defines named groups (`production`, `test`) usable with `--recipients`.
Config lives in the repo, so any recipient change requires a push to take effect.

---

## 9. Setup

```bash
git clone git@github.com:kiquefranco/marketintel.git && cd marketintel
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Dependencies: `anthropic`, `feedparser`, `requests`, `PyYAML`, `python-dotenv`, `numpy`, `openpyxl`.

Required keys in `.env`:

| Variable | Where it comes from |
|---|---|
| `GEMINI_API_KEY` | aistudio.google.com, billing enabled (default provider) |
| `ANTHROPIC_API_KEY` | console.anthropic.com (only if `llm.provider: anthropic`) |
| `YUTORI_API_KEY` | platform.yutori.com (`--no-yutori` to skip) |
| `SMTP_HOST` / `SMTP_PORT` / `SMTP_USER` / `SMTP_PASS` | Gmail App Password, not the account password |
| `EMAIL_FROM` | Sender shown on the digest (`um.marketintel.bot@gmail.com`) |
| `ALERT_EMAIL_TO` | Watchdog recipient (falls back to `SMTP_USER`) |

Recipients are **not** set in `.env`. See section 8.

New to the project: work through `docs/ONBOARDING.md` first. A bare `python run_briefing.py`
sends real email to real executives and spends real money.

---

## 10. Running

```bash
python scripts/verify_sources.py                       # check every RSS feed URL
python run_briefing.py --dry-run --no-yutori --no-llm  # free ingestion test
python run_briefing.py --dry-run --no-yutori           # full dry run -> data/briefings/
python scripts/score_report.py                         # why each story ranked where it did
python run_briefing.py --recipients test               # one shared send to the test group only
python run_briefing.py                                 # real run, sends every email
```

Flags:

* `--dry-run` builds and saves everything to `data/briefings/` and sends nothing. Dedup state is
  not consumed, so a dry run never burns a story.
* `--no-yutori` skips scout polling and deep dive.
* `--no-llm` is a development flag only. It produces a headline-only digest and bypasses
  reconciliation by design.
* `--recipients` takes a named list from `briefing.recipient_lists` or comma-separated addresses.
  It sends **one** shared briefing to exactly those addresses and **skips the per-profile send**,
  so a test run can never reach leadership.

Output files per run in `data/briefings/`: `<date>.html`, `<date>.json`, `<date>_digest.txt`,
`<date>_digest.html`, one `<date>_<profile>.html` per profile, and `<date>_comparison.html`.

---

## 11. Scheduling and automation

**GitHub's own `schedule:` cron is not the delivery mechanism.** It silently dropped the daily
run on 2026-06-16 and 06-17. The reliable trigger is an external cron service (cron-job.org)
calling the `workflow_dispatch` API, authenticated with a fine-grained PAT holding
`actions: read/write`. GitHub's cron remains as a free backup, and `guard_skip_if_ran.py` plus a
`concurrency` group ensure at most one send if both fire. Full setup: `CLOUD_SCHEDULING.md`.

| Workflow | When | What |
|---|---|---|
| `daily-briefing.yml` | ~6:07am ET weekdays (cron `7 10`, deliberately off the hour) | Guard, install, run pipeline, commit `data/intel.db` back, upload artifact |
| `briefing-watchdog.yml` | ~8:12am ET weekdays (cron `12 12`) | Verify a successful run today, else email `[ALERT]` |
| `scoring-insights.yml` | Mondays and Thursdays 14:00 UTC | Email the Excel scoring-insights workbook, commit accumulated sub-scores |
| `setup-scouts.yml` | Manual only | Recreate scouts under a new `YUTORI_API_KEY` and commit new scout IDs |

Yutori scouts scan once daily at 5am ET, ahead of the briefing.

Note the UTC crons assume EDT. During EST (November to March) the briefing needs `7 11` and the
watchdog `12 13` to hold the same local times.

**Dedup memory is durable because `data/intel.db` is committed back to the repo** after every
successful run (step "Persist updated database"). `.gitignore` excludes `data/*.db` but
force-includes `intel.db`. The daily commit also keeps the schedule from auto-pausing after 60
days of inactivity.

Local cron alternative:

```
7 10 * * 1-5 cd /path/to/marketintel && .venv/bin/python run_briefing.py
```

---

## 12. Costs

Gemini is a few cents per run (scoring, synthesis, embeddings, and the grounded Background
search), inside the free grounding allowance of 1,500 grounded queries per day. RSS and Google
News are free.

Yutori is the only material spend, at published rates:

| API | Rate | Trigger |
|---|---|---|
| Scouting | $0.35 per scout-run | One run per source per day, on Yutori's schedule |
| Browsing | $0.015 per step | Selected stories scoring >= `browse_min_relevance` (8), max 12 steps |
| Research | $0.35 per task | Stories scoring >= `research_min_relevance` (9), max 5/run |

**Budget: $100/month**, scoped to seven competitor scouts. Central estimate ~$92:

| Component | Monthly | Basis |
|---|---|---|
| Scouting | $74.48 | 7 sources x 30.4 daily runs x $0.35 |
| Browsing | $9.40 | ~5.7 briefed stories/day x 22 weekdays x ~5 steps |
| Research | $8.21 | ~1.1 tasks/day x 22 weekdays |

Two things matter when re-forecasting. Scouts bill on ~30.4 days, not 22, because they run daily
regardless of whether the weekday briefing fires. Browsing and research (~$18) do not scale with
source count, because they are driven by how many stories are *briefed*, which selection caps at
12/day. So the variable cost is ~$10.64 per monitored source per month on a ~$18 fixed base, and
scouting is roughly 80% of the bill.

**Current state: the Yutori key is unfunded.** `deep_dive.enabled` is `false`, so every briefing
is written from title and summary alone. The seven scout sources still poll and fail harmlessly.
Do not blame thin write-ups on the synthesis prompt before checking this. Only **two scouts are
actually live** (Baptist Health, Jackson Health); the other five are declared `type: yutori` in
`sources.yaml` and need `scripts/setup_scouts.py` to activate. Every extra scout is ~$10.64/month,
so re-run the budget before adding one.

---

## 13. Analysis and calibration layer

This sits on top of the live scoring and does not change how the daily briefing is scored.
Full treatment in `docs/AHP_ANALYSIS.md`.

`src/prioritize/subscores.py` runs a second cheap LLM pass that decomposes each article into
structured strategic dimensions (financial impact, strategic impact, competitive relevance,
operational impact, time sensitivity, proximity, actionability, direct relevance, magnitude),
stored as JSON on the article and stamped with `SUBSCORE_VERSION`. Changing the dimension list or
the prompt **requires bumping that version**, otherwise vectors missing the new key silently
score zero on it.

Those vectors feed two things:

* **AHP (prescriptive).** `config/ahp.yaml` holds pairwise judgments on Saaty's 1-9 scale.
  `python scripts/ahp.py --judgments` turns them into weights via the principal eigenvector and
  reports the Consistency Ratio; below 0.10 means the judgments are internally consistent.
* **Eigen-analysis (descriptive).** `python scripts/ahp.py --data` decomposes the correlation
  matrix of real article sub-scores to show which dimensions actually drive the rankings.

`scripts/ahp_to_excel.py` exports both with charts. `scripts/scoring_insights.py` produces the
recurring workbook on how the model is behaving.

---

## 14. Operations and gotchas

**Never run `git checkout -- data/intel.db`.** It has destroyed a day of ingested rows before
(2026-09-02). Every pull conflicts on `intel.db` because two writers (local and CI) touch a
binary file. Resolve with `python scripts/merge_intel_db.py`, never by picking a side. Use
`git pull --no-rebase --no-edit` so vim never opens.

**Git auth is SSH** (`git@github.com:kiquefranco/marketintel.git`), keyed by `~/.ssh/id_ed25519`
with the passphrase in the macOS keychain. The old plaintext `ghp_` PAT was removed from the
remote URL and deleted on GitHub on 2026-09-01. Do not reintroduce a token into the remote URL.
Revoking a delivery token has killed a full day of briefings.

**Python 3.9 on the local Mac.** Every module needs `from __future__ import annotations` for
`X | None` hints. CI runs 3.12.

**The Cowork sandbox has no outbound network** to `api.yutori.com`, Gemini or SMTP, and cannot
install PyPI packages. SQLite on the mounted folder throws "disk I/O error", so copy the DB to
`/tmp` to inspect it. Scouts, sends and scoring can only be tested locally or in CI. This is why
`scripts/send_html.py` and `scripts/send_yutori_tests.py` exist.

**Embedding batches chunk at 100.** Before the 2026-09-04 fix every `embed()` call 400'd and both
passes silently fell back to keyword dedup, which shipped four copies of one story. Confirm
semantic dedup is on from the run log rather than assuming it.

**Stale `.git/index.lock`** blocks git; `rm -f .git/index.lock` clears it.

**Terminal blocks in handoffs** should carry no `#` comments and no apostrophes, since they trap
an interactive zsh at a `quote>` prompt.

**Workflow Node version.** `checkout@v4`, `setup-python@v5` and `upload-artifact@v4` are pinned
across four workflow files. Runners default to Node 24 already, so this is hygiene, but the
`ACTIONS_ALLOW_USE_UNSECURE_NODE_VERSION` opt-out (never set here) ends 2026-09-23.

---

## 15. Status and open items

Live and automated end-to-end, sending real email every weekday: six strategy briefings, three
ambulatory briefings and one comparison diagnostic. Gemini billing enabled. Database holds
~5,100 articles since 2026-06-15, ~350 of them briefed.

Open:

1. **Fund the Yutori key or accept headline-only write-ups.** `deep_dive.enabled` stays false
   until then, and five of the seven in-scope scouts remain inactive.
2. **Close the source-coverage gap.** The pool is half local TV health news with almost no
   real-estate or construction coverage. This is a source-list problem, not a scoring one.
3. **Quiet feeds** still need cleanup (Rock Health, CDC, WHO, SFBJ, FL DOH):
   `python scripts/verify_sources.py`.
4. **Split the merged ambulatory profile** back into tailored Rafic and Weiss lenses when the
   dormant profiles are wanted.
5. **Repo size.** The tracked binary DB accumulates history; squash or BFG-prune if it grows.

---

## 16. Working on this repo

`CLAUDE.md` is the fast catch-up doc for a fresh session and reflects the current design; older
notes and diagrams elsewhere may be stale. `docs/claude_code_prompt.md` holds a ready onboarding
prompt.

Conventions:

* Python 3.9 compatible; stdlib plus `requirements.txt` only; small, mostly-pure modules.
* All pipeline state goes through SQLite. A source failure must never crash the run.
* Never hardcode sources, weights or org details in Python. They live in `config/`.
* Secrets only in `.env` locally or GitHub Actions secrets. Never commit them.
* Pull before you start, commit small, push often. A weights or rubric change gets a one-line
  rationale in the commit message and an entry in `PRIORITIZATION_CHANGELOG.md`.
