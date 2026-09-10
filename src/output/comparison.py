"""Prioritization comparison email: strategy briefing vs. ambulatory briefing.

A DIAGNOSTIC, not a briefing. It goes to the people who tune the scoring (see
briefing.comparison.recipients in settings.yaml), never to leadership, and it answers
one question: where did the two prioritizations disagree today, and why?

So the layout is divergence-first. The three buckets — sent by only one side, sent by
both — come before anything else, and each line carries BOTH lenses' scores plus the
rationale of the side that PASSED on the story. Story content is deliberately absent:
the two real briefings already carry it, and repeating it here would bury the only
thing this email exists to show.

Both passes decide tier 1 on `composite_score` (0-100), so the two columns are on the
same scale by construction: the house pass's composite and the profile pass's
`personal_composite` are both relevance x10, the second with keyword nudges applied.
"""
from __future__ import annotations
from html import escape

from .emailer import (AREA_COLORS, AREA_LABELS, BRAND, BRAND_TINT, DEFAULT_AREA_COLOR,
                      INK, MUTED)

# Divergence colours: one hue per "only this side" bucket, shared items stay neutral.
HOUSE_ACCENT = "#F47321"    # orange — strategy-only
PROF_ACCENT = "#005030"     # green  — ambulatory-only
SHARED_ACCENT = BRAND       # teal   — both (the shared briefing's own colour)


def _score10(value) -> str:
    """A 0-100 composite as the 0-10 number the bar is set in, one decimal.

    Unlike the reader-facing briefing badge (emailer._fmt_score, truncated to a whole
    number on purpose), the decimal is the POINT here: 7.9 vs 8.1 is exactly the kind of
    near-miss this email exists to expose.
    """
    if value is None or value == "":
        return "--"
    try:
        return f"{float(value) / 10.0:.1f}"
    except (TypeError, ValueError):
        return "--"


def _area_chip(area: str) -> str:
    bg, ontext = AREA_COLORS.get(area, DEFAULT_AREA_COLOR)
    return (f'<span style="background:{bg};color:{ontext};font-size:9px;font-weight:bold;'
            f'padding:1px 6px;border-radius:3px;white-space:nowrap">'
            f'{escape(AREA_LABELS.get(area, area or "--"))}</span>')


def _clip(text, limit: int = 190) -> str:
    t = " ".join(str(text or "").split())
    return t if len(t) <= limit else t[: limit - 1].rstrip(" ,;.") + "…"


def _pool_get(pool: dict, art: dict) -> dict:
    return (pool or {}).get(art.get("id")) or {}


def _sec(title: str, accent: str = BRAND) -> str:
    return (f'<h2 style="color:{accent};font-size:12px;margin:22px 0 6px;'
            f'text-transform:uppercase;letter-spacing:.04em">{escape(title)}</h2>')


def _tile(label: str, value: str, sub: str, accent: str) -> str:
    return (f'<td style="padding:0 6px 0 0;width:33%;vertical-align:top">'
            f'<div style="border-top:3px solid {accent};background:#FAFBFC;padding:8px 10px">'
            f'<div style="font-size:22px;font-weight:bold;color:{accent};line-height:1.1">'
            f'{escape(value)}</div>'
            f'<div style="font-size:11px;color:{INK};font-weight:bold;margin-top:2px">'
            f'{escape(label)}</div>'
            f'<div style="font-size:10px;color:{MUTED};margin-top:1px">{escape(sub)}</div>'
            f'</div></td>')


def _row(art: dict, *, rank: int | None, own_label: str, own_score,
         other_label: str, other_score, other_why: str, accent: str) -> str:
    """One story line: title, both lenses' scores, and the other lens's reasoning."""
    title = escape(str(art.get("title", "") or "(untitled)"))
    url = escape(str(art.get("url", "") or "#"))
    src = escape(str(art.get("source", "") or ""))
    rk = f'<span style="color:{MUTED};font-size:10px">{rank}.</span> ' if rank else ""
    scores = (
        f'<span style="background:{BRAND_TINT};color:{BRAND};font-size:10px;font-weight:bold;'
        f'padding:1px 7px;border-radius:10px;white-space:nowrap">'
        f'{escape(own_label)} {_score10(own_score)}</span> '
        f'<span style="background:#F1F2F4;color:{MUTED};font-size:10px;font-weight:bold;'
        f'padding:1px 7px;border-radius:10px;white-space:nowrap">'
        f'{escape(other_label)} {_score10(other_score)}</span>'
    )
    why = (f'<div style="font-size:10.5px;color:{MUTED};margin:3px 0 0">'
           f'<b style="color:{INK}">{escape(other_label)} lens:</b> {escape(_clip(other_why))}'
           f'</div>') if other_why else ""
    return (
        f'<div style="border-left:3px solid {accent};padding:6px 0 7px 9px;margin:0 0 8px">'
        f'<div style="font-size:12.5px;line-height:1.35">{rk}'
        f'<a href="{url}" style="color:{BRAND};text-decoration:none">{title}</a></div>'
        f'<div style="margin:4px 0 0">{scores} {_area_chip(art.get("area", ""))}'
        + (f' <span style="color:#AAB0B6;font-size:10px">{src}</span>' if src else "")
        + f'</div>{why}</div>'
    )


def _tier2_line(art: dict, accent: str) -> str:
    title = escape(str(art.get("title", "") or ""))
    url = escape(str(art.get("url", "") or "#"))
    return (f'<p style="margin:3px 0;font-size:11.5px">'
            f'<span style="color:{accent};font-weight:bold">&bull;</span> '
            f'<a href="{url}" style="color:{BRAND};text-decoration:none">{title}</a> '
            f'<span style="color:{MUTED}">{_score10(art.get("composite_score"))}</span></p>')


def _empty(text: str) -> str:
    return f'<p style="font-size:11.5px;color:{MUTED};margin:2px 0 0">{escape(text)}</p>'


def render_comparison_html(date_str: str, org_name: str, house: dict, profile: dict,
                           greeting: str | None = None) -> str:
    """Build the comparison email.

    `house` and `profile` are each:
        {"label": short column name, "sublabel": who receives that briefing,
         "cards":   [article dicts sent as full story cards],
         "runners": [article dicts sent in "Also worth noting"],
         "pool":    {article id: {"score": 0-100 composite, "why": rationale}}}
    `pool` is that side's view of EVERY candidate it scored, which is what lets a story
    the other side sent be shown with this side's number instead of a blank.
    """
    h_label, p_label = house.get("label", "Strategy"), profile.get("label", "Ambulatory")
    h_cards = list(house.get("cards") or [])
    p_cards = list(profile.get("cards") or [])
    h_pool, p_pool = house.get("pool") or {}, profile.get("pool") or {}

    h_ids = {a.get("id") for a in h_cards}
    p_ids = {a.get("id") for a in p_cards}
    shared_ids = h_ids & p_ids
    union = len(h_ids | p_ids)
    overlap = f"{round(100 * len(shared_ids) / union)}%" if union else "--"

    h_only = [a for a in h_cards if a.get("id") not in shared_ids]
    p_only = [a for a in p_cards if a.get("id") not in shared_ids]
    shared = [a for a in h_cards if a.get("id") in shared_ids]
    h_rank = {a.get("id"): i + 1 for i, a in enumerate(h_cards)}
    p_rank = {a.get("id"): i + 1 for i, a in enumerate(p_cards)}

    parts = [
        f'<div style="font-family:Arial,sans-serif;max-width:680px;margin:auto;color:{INK};'
        f'font-size:12px;line-height:1.4">',
        (f'<p style="font-size:12px;margin:0 0 3px">Good morning {escape(greeting)},</p>'
         if greeting else ''),
        f'<h1 style="color:{BRAND};font-size:16px;margin:0 0 2px">Prioritization comparison '
        f'&mdash; {escape(date_str)}</h1>',
        f'<p style="color:{MUTED};font-size:10px;margin:0 0 12px">{escape(org_name)} &middot; '
        f'Highly Confidential &middot; internal scoring diagnostic, not a briefing</p>',
    ]

    # Headline: how far apart the two lenses landed today.
    parts.append(
        '<table role="presentation" cellpadding="0" cellspacing="0" border="0" '
        'style="width:100%;border-collapse:separate;margin:0 0 4px"><tr>'
        + _tile(f"{h_label} only", str(len(h_only)),
                f"of {len(h_cards)} sent", HOUSE_ACCENT)
        + _tile("In both", str(len(shared)), f"{overlap} overlap", SHARED_ACCENT)
        + _tile(f"{p_label} only", str(len(p_only)),
                f"of {len(p_cards)} sent", PROF_ACCENT)
        + '</tr></table>'
    )
    parts.append(
        f'<p style="font-size:11px;color:{MUTED};margin:8px 0 0">'
        f'{escape(h_label)}: {escape(house.get("sublabel", ""))} &middot; '
        f'{escape(p_label)}: {escape(profile.get("sublabel", ""))}</p>'
    )

    # --- The three buckets ---
    parts.append(_sec(f"Only {h_label.lower()} sent it", HOUSE_ACCENT))
    if h_only:
        parts.append(f'<p style="font-size:11px;color:{MUTED};margin:0 0 8px">What the '
                     f'{escape(p_label.lower())} lens scored down.</p>')
        for a in h_only:
            other = _pool_get(p_pool, a)
            parts.append(_row(a, rank=h_rank.get(a.get("id")), own_label=h_label,
                              own_score=a.get("composite_score"), other_label=p_label,
                              other_score=other.get("score"), other_why=other.get("why", ""),
                              accent=HOUSE_ACCENT))
    else:
        parts.append(_empty("Nothing. Every story the strategy briefing sent also cleared "
                            "the ambulatory bar."))

    parts.append(_sec(f"Only {p_label.lower()} sent it", PROF_ACCENT))
    if p_only:
        parts.append(f'<p style="font-size:11px;color:{MUTED};margin:0 0 8px">What the role '
                     f'lens surfaced that the house ranking did not.</p>')
        for a in p_only:
            other = _pool_get(h_pool, a)
            parts.append(_row(a, rank=p_rank.get(a.get("id")), own_label=p_label,
                              own_score=a.get("composite_score"), other_label=h_label,
                              other_score=other.get("score"), other_why=other.get("why", ""),
                              accent=PROF_ACCENT))
    else:
        parts.append(_empty("Nothing unique to the ambulatory briefing today."))

    parts.append(_sec("Sent by both", SHARED_ACCENT))
    if shared:
        parts.append(f'<p style="font-size:11px;color:{MUTED};margin:0 0 8px">'
                     f'Agreement. Rank on each side in brackets.</p>')
        for a in shared:
            aid = a.get("id")
            p_hit = _pool_get(p_pool, a)
            parts.append(
                f'<div style="border-left:3px solid {SHARED_ACCENT};padding:6px 0 7px 9px;'
                f'margin:0 0 8px">'
                f'<div style="font-size:12.5px;line-height:1.35">'
                f'<a href="{escape(str(a.get("url") or "#"))}" '
                f'style="color:{BRAND};text-decoration:none">'
                f'{escape(str(a.get("title", "")))}</a></div>'
                f'<div style="margin:4px 0 0">'
                f'<span style="background:{BRAND_TINT};color:{BRAND};font-size:10px;'
                f'font-weight:bold;padding:1px 7px;border-radius:10px">'
                f'{escape(h_label)} {_score10(a.get("composite_score"))} '
                f'[#{h_rank.get(aid, "-")}]</span> '
                f'<span style="background:{BRAND_TINT};color:{BRAND};font-size:10px;'
                f'font-weight:bold;padding:1px 7px;border-radius:10px">'
                f'{escape(p_label)} {_score10(p_hit.get("score"))} '
                f'[#{p_rank.get(aid, "-")}]</span> {_area_chip(a.get("area", ""))}</div>'
                f'</div>'
            )
    else:
        parts.append(_empty("No story cleared both bars today."))

    # --- Second tier, titles only. Divergence here is cheap to scan and often the
    # earliest signal that a keyword list needs a nudge. ---
    h_run, p_run = list(house.get("runners") or []), list(profile.get("runners") or [])
    if h_run or p_run:
        parts.append(_sec('Also worth noting — second tier'))
        parts.append(
            '<table role="presentation" cellpadding="0" cellspacing="0" border="0" '
            'style="width:100%"><tr>'
            f'<td style="width:50%;vertical-align:top;padding-right:8px">'
            f'<p style="font-size:11px;font-weight:bold;color:{HOUSE_ACCENT};margin:0 0 4px">'
            f'{escape(h_label)} ({len(h_run)})</p>'
            + ("".join(_tier2_line(a, HOUSE_ACCENT) for a in h_run) or _empty("None."))
            + '</td>'
            f'<td style="width:50%;vertical-align:top;padding-left:8px">'
            f'<p style="font-size:11px;font-weight:bold;color:{PROF_ACCENT};margin:0 0 4px">'
            f'{escape(p_label)} ({len(p_run)})</p>'
            + ("".join(_tier2_line(a, PROF_ACCENT) for a in p_run) or _empty("None."))
            + '</td></tr></table>'
        )

    parts.append(
        f'<div style="margin-top:26px;border-top:1px solid #DDD;padding-top:10px;'
        f'font-size:10px;color:{MUTED};line-height:1.5">'
        f'<b style="color:{INK}">How to read this.</b> Both columns are the number each '
        f'pass ranks on, out of 10, from one ingestion and one house-scoring pass. '
        f'{escape(h_label)} is the house composite. {escape(p_label)} is the same articles '
        f're-scored against the ambulatory role description, plus that profile&rsquo;s '
        f'keyword nudges (+0.3 per interest hit, capped +0.6) &mdash; which is why a story '
        f'can clear its bar on a raw score below it. A blank score (--) means that side '
        f'never scored the article: it was dropped as a duplicate, or fell out of the '
        f'candidate pool before that pass ran. Story content is in the two briefings '
        f'themselves; this email only shows where they parted.</div></div>'
    )
    return "".join(parts)
