"""Offline test for the prioritization-comparison email (src/output/comparison.py plus
run_briefing's _comparison_group / _send_comparison wiring).

No network, no LLM, no DB — it builds two synthetic selections that exercise every branch
the real pass can produce, and asserts the rendered email says the right things:

  * a story only the strategy briefing sent, carrying the AMBULATORY score + rationale;
  * a story only the ambulatory briefing sent, carrying the STRATEGY score + rationale;
  * a story both sent, with each side's rank;
  * a story the other side never scored, rendered as "--" and never as "0.0";
  * a quiet house day (no cards at all), which must still produce an email;
  * group selection by profile name, and the fallback when the name is missing.

Run:  python3 scripts/test_comparison.py     (exit 0 = all good)
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Pure-function test; stub feed-ingestion deps if absent so it runs in any sandbox.
try:
    import feedparser  # noqa: F401
except ImportError:
    import types
    sys.modules["feedparser"] = types.ModuleType("feedparser")

import run_briefing  # noqa: E402
from src.output.comparison import render_comparison_html  # noqa: E402


def art(i, title, area, score, **kw):
    return {"id": i, "title": title, "url": f"https://example.com/{i}", "source": "Test Wire",
            "area": area, "composite_score": score, **kw}


BOTH = art(1, "Baptist breaks ground on Doral medical office building",
           "south_florida_competitive", 91)
HOUSE_ONLY = art(2, "Federal research funding cut hits academic centers",
                 "national_policy", 86)
PROF_ONLY = art(3, "Site-neutral payment rule finalized for outpatient billing",
                "national_policy", 84)
UNSCORED_BY_HOUSE = art(4, "Broward MOB portfolio changes hands", "south_florida_competitive", 82)

HOUSE = {
    "label": "Strategy", "sublabel": "house scoring",
    "cards": [BOTH, HOUSE_ONLY],
    "runners": [art(5, "Health system names new CFO", "national_policy", 66)],
    "pool": {
        1: {"score": 91, "why": "Competitor capital commitment in the service area."},
        2: {"score": 86, "why": "Direct exposure through the research engine."},
        3: {"score": 58, "why": "Reimbursement color; nothing for strategy to act on yet."},
        # id 4 deliberately absent: the house pass never scored it.
    },
}
PROF = {
    "label": "Ambulatory", "sublabel": "role-scored",
    "cards": [BOTH, PROF_ONLY, UNSCORED_BY_HOUSE],
    "runners": [],
    "pool": {
        1: {"score": 88, "why": "Outpatient facility development by a competitor."},
        2: {"score": 31, "why": "Research funding is another leader's remit."},
        3: {"score": 84, "why": "Changes the capital case for an outpatient site."},
        4: {"score": 82, "why": "Regional healthcare real estate transaction."},
    },
}

FAIL = []


def check(cond, msg):
    if not cond:
        FAIL.append(msg)


html = render_comparison_html("Tuesday, September 08, 2026", "Test Health System", HOUSE, PROF)

check("Only strategy sent it" in html, "missing the strategy-only bucket heading")
check("Only ambulatory sent it" in html, "missing the ambulatory-only bucket heading")
check("Sent by both" in html, "missing the shared bucket heading")

# Bucket membership: each story appears under the right heading, in order.
order = [html.index("Only strategy sent it"), html.index("Only ambulatory sent it"),
         html.index("Sent by both")]
check(order == sorted(order), "buckets are out of order (divergence must come first)")
check(order[0] < html.index(HOUSE_ONLY["title"]) < order[1],
      "the strategy-only story is not in the strategy-only bucket")
check(order[1] < html.index(PROF_ONLY["title"]) < order[2],
      "the ambulatory-only story is not in the ambulatory-only bucket")
check(html.index(BOTH["title"]) > order[2] or html.count(BOTH["title"]) > 1,
      "the shared story never appears in the shared bucket")

# Both lenses on every line, and the PASSING side's reasoning is what is shown.
check("Research funding is another leader" in html,
      "the ambulatory rationale is missing from the strategy-only line")
check("nothing for strategy to act on" in html,
      "the strategy rationale is missing from the ambulatory-only line")
check("Strategy 8.6" in html and "Ambulatory 3.1" in html,
      "the strategy-only line does not carry both scores")
check("Ambulatory 8.4" in html and "Strategy 5.8" in html,
      "the ambulatory-only line does not carry both scores")

# A story the other side never scored reads as unknown, NOT as a zero.
check("Strategy --" in html, "an unscored article rendered as a number instead of --")
check("Strategy 0.0" not in html, "an unscored article rendered as 0.0")

# Ranks on the shared line.
check("[#1]" in html, "shared story is missing its rank on each side")

# Overlap arithmetic: 1 shared of 4 distinct stories.
check("25% overlap" in html, "overlap percentage is wrong")

# Second tier renders per side, including the empty one.
check("Health system names new CFO" in html, "house second tier missing")
check("Ambulatory (0)" in html, "empty second tier not labelled")

# Quiet house day: no cards at all must still render, and must not claim agreement.
quiet = render_comparison_html("Tuesday, September 08, 2026", "Test Health System",
                               {"label": "Strategy", "sublabel": "", "cards": [],
                                "runners": [], "pool": HOUSE["pool"]}, PROF)
check("No story cleared both bars today." in quiet, "quiet day does not say the bars were unmet")
check(PROF_ONLY["title"] in quiet, "quiet day dropped the ambulatory-only stories")

# Group selection.
recs = [{"members": [{"name": "Other-Role"}], "label": "Other"},
        {"members": [{"name": "Ambulatory-Rafic"}, {"name": "Ambulatory-Weiss"}],
         "label": "Ambulatory"}]
check(run_briefing._comparison_group(recs, "Ambulatory-Weiss")["label"] == "Ambulatory",
      "profile name did not select its own group")
check(run_briefing._comparison_group(recs, "Nobody")["label"] == "Other",
      "unknown profile name did not fall back to the first group")
check(run_briefing._comparison_group([], "Ambulatory-Rafic") is None,
      "no groups should yield None")

out = Path(__file__).resolve().parent.parent / "data" / "briefings"
out.mkdir(parents=True, exist_ok=True)
(out / "_comparison_test.html").write_text(html, encoding="utf-8")

if FAIL:
    print("FAILED:")
    for f in FAIL:
        print("  -", f)
    sys.exit(1)
print(f"OK — all checks passed. Sample written to {out / '_comparison_test.html'}")
