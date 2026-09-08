#!/usr/bin/env python3
"""One-off LOCAL BACKTEST: re-score a HISTORICAL day's already-ingested article pool
against one configured profile, without touching the live daily pipeline.

Safety, by design:
  - Never sends email. There is no SMTP code in this script at all.
  - Never writes composite_score, subscores, or briefed_on -- those belong to the
    house scorer and are left exactly as they are.
  - The ONLY write is to the `profile_scores` table, and only for the profile name
    you pass in. Since "Ambulatory-Rafic" / "Ambulatory-Weiss" / "Ambulatory-Maura"
    have never been scored before, the first run can only ADD new rows -- it cannot
    overwrite any other profile's cached scores. Re-running it just re-uses/updates
    its own rows.
  - Does not touch config/profiles.yaml or any dated file in data/briefings/ -- the
    optional synthesized output is saved under a "backtest_" prefix so it can never
    collide with a real production briefing filename.

Cost: one Gemini scoring call per NEW article in the day's pool (batched, same as
the daily pipeline) -- for a single day's pool (tens of articles) this is a few
cents. Add --synthesize for one extra synthesis call to also see the narrative
write-up; leave it off for the cheapest possible check (just the ranked list).

Usage (run from the marketintel/ project root, with your normal venv/deps active):
    python scripts/personalize.py --list-profiles         # sanity-check profile names first
    python scripts/backtest_profile.py --date 2026-08-05 --profile Ambulatory-Rafic
    python scripts/backtest_profile.py --date 2026-08-05 --profile Ambulatory-Rafic --synthesize

To fully undo everything this script can possibly write, at any time:
    DELETE FROM profile_scores WHERE profile IN
        ('Ambulatory-Rafic','Ambulatory-Weiss','Ambulatory-Maura');
"""
from __future__ import annotations
import argparse
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import config, store, profiles as P             # noqa: E402
from src.llm_client import LLMClient                      # noqa: E402
from src.output import emailer, synthesize                # noqa: E402
from src.prioritize import profile_relevance as PR        # noqa: E402


def day_pool(con, date_str: str) -> list[dict]:
    """Already-scored articles fetched on this ONE calendar day (UTC)."""
    start = f"{date_str}T00:00:00"
    end = (datetime.strptime(date_str, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%dT00:00:00")
    rows = con.execute(
        "SELECT * FROM articles WHERE composite_score IS NOT NULL "
        "AND fetched >= ? AND fetched < ? ORDER BY composite_score DESC",
        (start, end),
    ).fetchall()
    return [dict(r) for r in rows]


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                  formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--date", required=True, help="YYYY-MM-DD, e.g. 2026-08-05")
    ap.add_argument("--profile", required=True,
                     help="a profile 'name' from config/profiles.yaml, e.g. Ambulatory-Rafic")
    ap.add_argument("--synthesize", action="store_true",
                     help="also build the full narrative briefing HTML (extra LLM call, extra cost). Off by default.")
    args = ap.parse_args()

    cfg = config.load_all()
    all_profiles, defaults = P.load_profiles()
    match = [p for p in all_profiles if p["name"] == args.profile]
    if not match:
        print(f"No profile named {args.profile!r} in config/profiles.yaml.")
        print(f"Available: {[p['name'] for p in all_profiles]}")
        return
    profile = {**defaults, **match[0]}
    profile["_weights"] = P.dimension_weights(profile)

    if not P.uses_semantic_scoring(profile):
        print(f"{args.profile!r} has no role_description -- nothing semantic to backtest.")
        return

    con = store.connect()
    pool = day_pool(con, args.date)
    print(f"{args.date}: {len(pool)} already-scored articles in the house pool.")
    if not pool:
        print("Nothing to backtest -- no scored articles ingested on that date.")
        return

    client = LLMClient(cfg["settings"]["llm"]["provider"])
    models = cfg["settings"]["llm"]["models"][cfg["settings"]["llm"]["provider"]]

    PR.ensure_table(con)
    cached = PR.load_all(con, profile["name"])
    todo = [a for a in pool if a["id"] not in cached]
    if todo:
        print(f"Scoring {len(todo)} new articles against {args.profile!r}'s role_description "
              f"(additive only -- no other profile's cached scores are touched)...")
        results = PR.score_batch(client, models["scoring"], cfg["settings"]["org"], profile, todo)
        for art, (score, why) in zip(todo, results):
            PR.save(con, art["id"], profile["name"], score, why)
            cached[art["id"]] = (score, why)
        con.commit()
    else:
        print(f"All {len(pool)} articles already have a cached score for {args.profile!r} "
              f"from a prior run of this script.")

    for a in pool:
        hit = cached.get(a["id"])
        if hit:
            a["profile_score"], a["profile_why"] = hit

    ranked = P.rank_for_profile(profile, cfg["weights"], pool)
    threshold = profile.get("threshold", cfg["weights"].get("score_threshold", 55))
    print(f"\n{len(ranked)} of {len(pool)} stories clear {args.profile!r}'s threshold ({threshold}):\n")
    for a in ranked:
        interests, avoid = P.keyword_hits(profile, a)
        tags = ""
        if interests:
            tags += f"  [+{','.join(interests)}]"
        if avoid:
            tags += f"  [-{','.join(avoid)}]"
        print(f"  {a['personal_composite']:>5.1f}  (LLM {a['profile_score']:.1f})  {a['title']}{tags}")

    if args.synthesize:
        if not ranked:
            print("\nNothing above threshold -- skipping synthesis.")
            return
        settings = cfg["settings"]
        date_h = datetime.strptime(args.date, "%Y-%m-%d").strftime("%A, %B %d, %Y")
        briefing = synthesize.build_briefing(
            client, models["synthesis"], settings["llm"]["max_tokens_synthesis"],
            settings["org"], settings["key_questions"], ranked,
            style=settings["briefing"].get("synthesis_style", ""))
        html = emailer.render_html(briefing, date_h, settings["org"]["name"], [],
                                    greeting=profile.get("display_name") or profile.get("name", ""))
        out_dir = config.DATA_DIR / "briefings"
        out_dir.mkdir(exist_ok=True)
        out_path = out_dir / f"backtest_{args.date}_{args.profile}.html"
        out_path.write_text(html, encoding="utf-8")
        (out_dir / f"backtest_{args.date}_{args.profile}.json").write_text(
            json.dumps(briefing, indent=2), encoding="utf-8")
        print(f"\nSaved (not sent): {out_path}")


if __name__ == "__main__":
    main()
