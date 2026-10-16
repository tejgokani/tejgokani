#!/usr/bin/env python3
"""Generate the profile's SVG assets from live GitHub data.

    GITHUB_TOKEN=$(gh auth token) python3 scripts/build_assets.py

Writes assets/{dark,light}/*.svg: hero banner, project cards, a radial
contribution radar with real stats, and a terminal feed of recent activity.
Plain SVG + CSS only, so it animates inside GitHub's <img> sandbox.
Standard library only; the daily workflow re-runs this and commits any change.
"""
import json
import os
import urllib.parse
import urllib.request
from collections import Counter
from datetime import date, datetime
from math import cos, radians, sin
from pathlib import Path
from xml.sax.saxutils import escape

USER = "tejgokani"
ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "assets"
# Team/course repos whose merged PRs are internal, not upstream fixes.
EXCLUDE_UPSTREAM = {"harxhe/kernel-module-rootkit-detector"}
MONO = "'JetBrains Mono','Fira Code','SF Mono',Menlo,Consolas,monospace"
SANS = "-apple-system,'Segoe UI',Helvetica,Arial,sans-serif"

THEMES = {
    "dark": dict(
        bg="#06090a", dot="#16312c", ring="#12302a", border="#16302b", vignette="#000000", vig_op=0.85,
        title="#d7fff6", mute="#5f7a75", mute2="#4d6762", accent="#2affc9",
        name_a="#ffffff", name_b="#b9fff0", name_c="#2affc9",
        card_bg="#080c0d", card_stroke="#18292a", card_name="#e9fffa", desc="#9fb3af", lang="#7f9a95",
        empty="#0e1b19", levels=["#0e4b40", "#13806a", "#1fc7a0", "#2affc9"],
        term_bg="#06090a", term_bar="#0c1214", row="#a9bfba", rowdim="#566f6a",
    ),
    "light": dict(
        bg="#f3faf8", dot="#cfe6e0", ring="#bcdad2", border="#c4dfd8", vignette="#cfe6e0", vig_op=0.9,
        title="#063b32", mute="#5b7d76", mute2="#6c8d86", accent="#00957a",
        name_a="#02201b", name_b="#054d40", name_c="#00957a",
        card_bg="#ffffff", card_stroke="#cfe3de", card_name="#052e27", desc="#3f5f58", lang="#4d6e67",
        empty="#e2efec", levels=["#b6e8dc", "#6fd1ba", "#1fae8f", "#00785d"],
        term_bg="#f8fdfc", term_bar="#e5f2ef", row="#2c4a43", rowdim="#7a9992",
    ),
}


# ------------------------------------------------------------------ data

def _get(url: str, data: bytes | None = None) -> dict:
    req = urllib.request.Request(url, data=data, headers={"Accept": "application/vnd.github+json"})
    if token := os.environ.get("GITHUB_TOKEN"):
        req.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def fetch_calendar() -> list[list[dict]]:
    q = ('{user(login:"%s"){contributionsCollection{contributionCalendar{weeks{contributionDays'
         '{date contributionCount contributionLevel weekday}}}}}}' % USER)
    res = _get("https://api.github.com/graphql", json.dumps({"query": q}).encode())
    return [w["contributionDays"] for w in
            res["data"]["user"]["contributionsCollection"]["contributionCalendar"]["weeks"]]


def search(kind: str, q: str, sort: str) -> list[dict]:
    qs = urllib.parse.urlencode({"q": q, "sort": sort, "order": "desc", "per_page": 50})
    return _get(f"https://api.github.com/search/{kind}?{qs}")["items"]


def fetch_upstream() -> list[dict]:
    items = search("issues", f"author:{USER} is:pr is:merged -user:{USER}", "updated")
    out = []
    for it in items:
        repo = it["repository_url"].split("/repos/")[1]
        if repo not in EXCLUDE_UPSTREAM:
            when = (it.get("pull_request") or {}).get("merged_at") or it["closed_at"]
            out.append(dict(kind="merged", repo=repo, msg=it["title"], date=when[:10]))
    return out


def fetch_commits() -> list[dict]:
    items = search("commits", f"author:{USER}", "author-date")
    out, per_repo = [], Counter()
    for it in items:
        msg = it["commit"]["message"].split("\n")[0]
        repo = it["repository"]["full_name"]
        if msg.startswith("Merge ") or per_repo[repo] >= 3:
            continue
        per_repo[repo] += 1
        out.append(dict(kind="commit", repo=repo, msg=msg, date=it["commit"]["author"]["date"][:10]))
    return out


def stats(weeks: list[list[dict]], upstream: list[dict]) -> dict:
    days = [d for w in weeks for d in w]
    counts = [d["contributionCount"] for d in days]
    longest = run = 0
    for c in counts:
        run = run + 1 if c else 0
        longest = max(longest, run)
    # current streak: today may still be empty, so start from yesterday in that case
    i = len(counts) - 1
    if i >= 0 and counts[i] == 0:
        i -= 1
    cur = 0
    while i >= 0 and counts[i]:
        cur += 1
        i -= 1
    busiest = max(days, key=lambda d: d["contributionCount"])
    by_wd = Counter()
    for d in days:
        by_wd[d["weekday"]] += d["contributionCount"]
    names = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"]
    return dict(
        total=sum(counts), longest=longest, current=cur,
        busiest=f"{busiest['contributionCount']} on {fmt(busiest['date'])}",
        weekday=names[by_wd.most_common(1)[0][0]],
        upstream=len(upstream), projects=len({u["repo"] for u in upstream}),
    )


def fmt(iso: str) -> str:
    return datetime.strptime(iso, "%Y-%m-%d").strftime("%b %-d")


# ------------------------------------------------------------------ hero

PHRASES = [
    "security tooling in Rust, Go and C",
    "fixes merged into nuclei, falco, crowdsec, express",
    "shipping: remotectl / redoubt / MYCROFT",
]
CHAR_W = 13.2  # px per monospace glyph at 22px (enforced with textLength)


def hero(t: dict) -> str:
    cycle, n = 15, len(PHRASES)
    seg = 100 / n
    css, clips, texts = [], [], []
    for i, phrase in enumerate(PHRASES):
        w = round(len(phrase) * CHAR_W, 1)
        s = i * seg
        keys = [(0, 0), (s, 0), (s + seg * 0.38, w), (s + seg * 0.9, w), (s + seg * 0.97, 0), (100, 0)]
        keys = list(dict.fromkeys(keys))
        kf = "".join(f"{p:.2f}%{{width:{v}px}}" for p, v in keys)
        ckf = "".join(f"{p:.2f}%{{transform:translateX({v}px)}}" for p, v in keys)
        # the caret is only visible during its own phrase's window
        vis = f"0%{{opacity:1}}{s + seg * 0.95:.2f}%{{opacity:0}}" if i == 0 else \
              f"0%{{opacity:0}}{s:.2f}%{{opacity:1}}{s + seg * 0.95:.2f}%{{opacity:0}}"
        css.append(
            f"@keyframes w{i}{{{kf}}} @keyframes c{i}{{{ckf}}} @keyframes v{i}{{{vis}}}"
            f".w{i}{{animation:w{i} {cycle}s steps({len(phrase)},end) infinite}}"
            f".c{i}{{animation:c{i} {cycle}s steps({len(phrase)},end) infinite,v{i} {cycle}s step-end infinite}}"
        )
        clips.append(f'<clipPath id="cp{i}"><rect x="48" y="196" height="34" class="w{i}" width="0"/></clipPath>')
        texts.append(
            f'<text x="48" y="220" class="mono" font-size="22" fill="{t["title"]}" '
            f'textLength="{w}" lengthAdjust="spacingAndGlyphs" clip-path="url(#cp{i})">{escape(phrase)}</text>'
            f'<rect x="48" y="200" width="9" height="26" fill="{t["accent"]}" class="c{i}" opacity="0.9"/>'
        )
    dots = "".join(f'<circle cx="{x}" cy="{y}" r="1.4" fill="{t["dot"]}"/>'
                   for x in range(24, 900, 28) for y in range(20, 320, 28))
    blips = "".join(
        f'<circle cx="{x}" cy="{y}" r="4" fill="{t["accent"]}" class="blip" style="animation-delay:{d}s"/>'
        for x, y, d in [(790, 110, 0), (690, 215, 2.6), (770, 235, 5.1), (655, 120, 6.4)])
    return f"""<svg width="900" height="320" viewBox="0 0 900 320" fill="none" xmlns="http://www.w3.org/2000/svg">
<title>Tej Gokani</title>
<defs>
  <linearGradient id="name" x1="0" y1="0" x2="1" y2="0">
    <stop offset="0" stop-color="{t['name_a']}"/><stop offset="0.6" stop-color="{t['name_b']}"/><stop offset="1" stop-color="{t['name_c']}"/>
  </linearGradient>
  <linearGradient id="sweep" x1="0" y1="0" x2="1" y2="0">
    <stop offset="0" stop-color="{t['accent']}" stop-opacity="0"/><stop offset="1" stop-color="{t['accent']}" stop-opacity="0.4"/>
  </linearGradient>
  <radialGradient id="fade" cx="0.5" cy="0.5" r="0.7">
    <stop offset="0.5" stop-color="{t['vignette']}" stop-opacity="0"/><stop offset="1" stop-color="{t['vignette']}" stop-opacity="{t['vig_op']}"/>
  </radialGradient>
  {''.join(clips)}
  <style>
    .mono{{font-family:{MONO}}} .sans{{font-family:{SANS}}}
    .blip{{animation:blip 8s ease-out infinite;opacity:0}}
    @keyframes blip{{0%,8%{{opacity:0;r:2}}10%{{opacity:1;r:4}}30%{{opacity:0;r:11}}100%{{opacity:0}}}}
    {''.join(css)}
  </style>
</defs>
<rect width="900" height="320" rx="14" fill="{t['bg']}"/>
{dots}
<rect width="900" height="320" rx="14" fill="url(#fade)"/>
<g stroke="{t['ring']}" stroke-width="1">
  <circle cx="730" cy="160" r="52"/><circle cx="730" cy="160" r="96"/><circle cx="730" cy="160" r="140"/>
  <path d="M590 160H870M730 20V300" stroke-dasharray="3 6"/>
</g>
<g>
  <path d="M730 160 L730 20 A140 140 0 0 1 829 61 Z" fill="url(#sweep)"/>
  <animateTransform attributeName="transform" type="rotate" from="0 730 160" to="360 730 160" dur="8s" repeatCount="indefinite"/>
</g>
<circle cx="730" cy="160" r="4" fill="{t['accent']}"/>
{blips}
<text x="48" y="92" class="mono" font-size="14" fill="{t['mute']}">~/tejgokani <tspan fill="{t['accent']}">$</tspan> whoami</text>
<text x="48" y="168" class="sans" font-size="68" font-weight="800" letter-spacing="-1.5" fill="url(#name)">Tej Gokani</text>
{''.join(texts)}
<text x="48" y="278" class="mono" font-size="13" fill="{t['mute2']}">full-stack developer  /  open-source contributor  /  bug hunter</text>
<rect x="0.5" y="0.5" width="899" height="319" rx="13.5" stroke="{t['border']}"/>
</svg>
"""


# ------------------------------------------------------------------ cards

PROJECTS = [
    dict(name="remotectl", lang="Rust · Kotlin", color="#f74c00",
         lines=["Control your laptop from your phone: lock, live", "stats, apps, terminal. End-to-end encrypted."],
         tag="homebrew tap · Android app"),
    dict(name="redoubt", lang="C", color="#8a96a3",
         lines=["Kernel-module rootkit detector for Linux & macOS.", "No dependencies, no VM. Catches what hides."],
         tag="plain C"),
    dict(name="MYCROFT", lang="Rust", color="#f74c00",
         lines=["The operating system for a pentest engagement:", "scope guard, evidence log, one-command report."],
         tag="homebrew tap"),
    dict(name="ShipCheck", lang="Go", color="#00add8",
         lines=["Post-session audit for AI coding agents: cost,", "heatmap and security scan. Zero API calls."],
         tag="★ 2"),
    dict(name="TermiBase", lang="Python", color="#3572a5",
         lines=["Terminal SQL playground that shows how queries", "are parsed, planned and executed."],
         tag="★ 6"),
    dict(name="winstonOSINT", lang="TypeScript", color="#3178c6",
         lines=["Open-source OSINT tracker: live flights, ships,", "news and markets on one map. Web + Electron."],
         tag="Electron"),
]


def card(p: dict, idx: int, t: dict) -> str:
    lang_w = len(p["lang"]) * 7.4 + 22
    return f"""<svg width="440" height="132" viewBox="0 0 440 132" fill="none" xmlns="http://www.w3.org/2000/svg">
<title>{escape(p['name'])}</title>
<defs>
  <linearGradient id="bar" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="{t['accent']}"/><stop offset="1" stop-color="{t['accent']}" stop-opacity="0.1"/></linearGradient>
  <linearGradient id="glint" x1="0" y1="0" x2="1" y2="0"><stop offset="0" stop-color="{t['accent']}" stop-opacity="0"/><stop offset="0.5" stop-color="{t['accent']}" stop-opacity="0.8"/><stop offset="1" stop-color="{t['accent']}" stop-opacity="0"/></linearGradient>
  <clipPath id="clip"><rect width="440" height="132" rx="12"/></clipPath>
  <style>.m{{font-family:{MONO}}} .s{{font-family:{SANS}}}
  .g{{animation:g 6s ease-in-out infinite;animation-delay:{idx * 0.7}s}} @keyframes g{{0%{{transform:translateX(-180px)}}60%,100%{{transform:translateX(460px)}}}}</style>
</defs>
<rect x="0.5" y="0.5" width="439" height="131" rx="11.5" fill="{t['card_bg']}" stroke="{t['card_stroke']}"/>
<g clip-path="url(#clip)"><rect class="g" y="0" width="180" height="2" fill="url(#glint)"/></g>
<rect x="0" y="22" width="3" height="42" rx="1.5" fill="url(#bar)"/>
<text x="24" y="40" class="m" font-size="18" font-weight="700" fill="{t['card_name']}">{escape(p['name'])}</text>
<g transform="translate({440 - 24 - lang_w:.1f},26)">
  <circle cx="6" cy="9" r="4.5" fill="{p['color']}"/>
  <text x="18" y="13" class="m" font-size="12" fill="{t['lang']}">{escape(p['lang'])}</text>
</g>
<text x="24" y="70" class="s" font-size="13.5" fill="{t['desc']}">{escape(p['lines'][0])}</text>
<text x="24" y="90" class="s" font-size="13.5" fill="{t['desc']}">{escape(p['lines'][1])}</text>
<text x="24" y="116" class="m" font-size="11.5" fill="{t['accent']}" opacity="0.9">{escape(p['tag'])}</text>
</svg>
"""


# ------------------------------------------------------------------ radar

LEVELS = {"NONE": -1, "FIRST_QUARTILE": 0, "SECOND_QUARTILE": 1, "THIRD_QUARTILE": 2, "FOURTH_QUARTILE": 3}


def _pt(cx: float, cy: float, r: float, a: float) -> str:
    return f"{cx + r * cos(radians(a)):.1f} {cy + r * sin(radians(a)):.1f}"


def _sector(cx: float, cy: float, r1: float, r2: float, a0: float, a1: float) -> str:
    return (f"M{_pt(cx, cy, r2, a0)}A{r2:.1f} {r2:.1f} 0 0 1 {_pt(cx, cy, r2, a1)}"
            f"L{_pt(cx, cy, r1, a1)}A{r1:.1f} {r1:.1f} 0 0 0 {_pt(cx, cy, r1, a0)}Z")


def radar(weeks: list[list[dict]], s: dict, t: dict) -> str:
    cx, cy, r0, rw = 200, 190, 46, 15
    nw = len(weeks)
    step = (360 - 8) / nw
    by_level: dict[int, list[str]] = {i: [] for i in range(-1, 4)}
    for wi, week in enumerate(weeks):
        a0 = -90 + 4 + wi * step + 0.35
        a1 = a0 + step - 0.7
        for d in week:
            r1 = r0 + d["weekday"] * rw + 1
            by_level[LEVELS[d["contributionLevel"]]].append(_sector(cx, cy, r1, r1 + rw - 2, a0, a1))
    cells = "".join(
        f'<path fill="{t["empty"] if lv < 0 else t["levels"][lv]}" d="{"".join(paths)}"/>'
        for lv, paths in by_level.items() if paths)
    rows = [
        ("longest streak", f"{s['longest']} days"),
        ("current streak", f"{s['current']} days"),
        ("busiest day", s["busiest"]),
        ("most active", s["weekday"]),
        ("merged upstream", f"{s['upstream']} PRs / {s['projects']} projects"),
    ]
    row_svg = "".join(
        f'<text x="440" y="{208 + i * 28}" class="m" font-size="13" fill="{t["mute"]}">{k}</text>'
        f'<text x="600" y="{208 + i * 28}" class="m" font-size="14" font-weight="700" fill="{t["accent"]}">{escape(v)}</text>'
        for i, (k, v) in enumerate(rows))
    return f"""<svg width="900" height="380" viewBox="0 0 900 380" fill="none" xmlns="http://www.w3.org/2000/svg">
<title>Contribution radar: the last year of GitHub activity, one ring per weekday</title>
<defs>
  <style>.m{{font-family:{MONO}}} .s{{font-family:{SANS}}}</style>
</defs>
<rect width="900" height="380" rx="14" fill="{t['bg']}"/>
<rect x="0.5" y="0.5" width="899" height="379" rx="13.5" stroke="{t['border']}"/>
<g stroke="{t['ring']}" stroke-width="1"><circle cx="{cx}" cy="{cy}" r="{r0 - 6}"/><circle cx="{cx}" cy="{cy}" r="{r0 + 7 * rw + 6}"/></g>
{cells}
<g>
  <path d="M{cx} {cy}L{cx} {cy - 170}A170 170 0 0 1 {_pt(cx, cy, 170, -50)}Z" fill="{t['accent']}" opacity="0.10"/>
  <path d="M{cx} {cy}L{cx} {cy - 170}" stroke="{t['accent']}" stroke-width="1.5" opacity="0.55"/>
  <animateTransform attributeName="transform" type="rotate" from="0 {cx} {cy}" to="360 {cx} {cy}" dur="10s" repeatCount="indefinite"/>
</g>
<text x="{cx}" y="{cy + 5}" text-anchor="middle" class="m" font-size="14" fill="{t['mute']}">12 mo</text>
<text x="440" y="86" class="m" font-size="13" fill="{t['mute']}">~/tejgokani <tspan fill="{t['accent']}">$</tspan> radar --last-year</text>
<text x="440" y="158" class="s" font-size="62" font-weight="800" letter-spacing="-1.5" fill="{t['accent']}">{s['total']}</text>
<text x="440" y="184" class="m" font-size="13" fill="{t['mute']}">contributions in the last 12 months</text>
{row_svg}
<g class="m" font-size="11" fill="{t['mute2']}">
  <text x="440" y="352">less</text>
  {''.join(f'<rect x="{476 + i * 16}" y="342" width="12" height="12" rx="2" fill="{c}"/>' for i, c in enumerate([t['empty']] + t['levels']))}
  <text x="{476 + 5 * 16 + 6}" y="352">more</text>
  <text x="{476 + 5 * 16 + 48}" y="352">· inner ring Sun, outer ring Sat</text>
</g>
</svg>
"""


# ------------------------------------------------------------------ feed

KIND = {"merged": ("merged", "accent"), "commit": ("commit", "row")}
MSG_MAX = 64


def clip(s: str, n: int) -> str:
    return s if len(s) <= n else s[: n - 1].rstrip() + "…"


def feed(events: list[dict], t: dict) -> str:
    rh, top = 26, 62
    h = top + len(events) * rh + 40
    rows = []
    for i, e in enumerate(events):
        label, color = KIND[e["kind"]]
        y = top + i * rh
        rows.append(
            f'<g class="r" style="animation-delay:{0.35 + i * 0.28:.2f}s">'
            f'<text x="28" y="{y}" class="m" font-size="12.5" fill="{t["rowdim"]}">{fmt(e["date"])}</text>'
            f'<text x="92" y="{y}" class="m" font-size="12.5" font-weight="700" fill="{t[color]}">{label}</text>'
            f'<text x="160" y="{y}" class="m" font-size="12.5" fill="{t["mute"]}">{escape(clip(e["repo"], 28))}</text>'
            f'<text x="388" y="{y}" class="m" font-size="12.5" fill="{t["row"]}">{escape(clip(e["msg"], MSG_MAX))}</text>'
            f'</g>')
    end_delay = 0.35 + len(events) * 0.28
    return f"""<svg width="900" height="{h}" viewBox="0 0 900 {h}" fill="none" xmlns="http://www.w3.org/2000/svg">
<title>Recent public activity, generated from the GitHub API</title>
<defs>
  <clipPath id="c"><rect width="900" height="{h}" rx="14"/></clipPath>
  <style>.m{{font-family:{MONO}}}
  .r{{opacity:0;animation:in .35s ease-out forwards}} @keyframes in{{from{{opacity:0;transform:translateX(-6px)}}to{{opacity:1;transform:none}}}}
  .cur{{animation:blink 1s steps(2,start) infinite}} @keyframes blink{{to{{visibility:hidden}}}}</style>
</defs>
<rect width="900" height="{h}" rx="14" fill="{t['term_bg']}"/>
<g clip-path="url(#c)"><rect width="900" height="36" fill="{t['term_bar']}"/></g>
<circle cx="24" cy="18" r="5" fill="#ff5f57"/><circle cx="44" cy="18" r="5" fill="#febc2e"/><circle cx="64" cy="18" r="5" fill="#28c840"/>
<text x="450" y="22" text-anchor="middle" class="m" font-size="12" fill="{t['mute']}">tejgokani: activity.log</text>
{''.join(rows)}
<g class="r" style="animation-delay:{end_delay:.2f}s">
  <text x="28" y="{top + len(events) * rh + 14}" class="m" font-size="12.5" fill="{t['accent']}">$ <tspan fill="{t['mute']}">tail -f activity.log</tspan></text>
  <rect class="cur" x="196" y="{top + len(events) * rh + 3}" width="8" height="15" fill="{t['accent']}"/>
</g>
<rect x="0.5" y="0.5" width="899" height="{h - 1}" rx="13.5" stroke="{t['border']}"/>
</svg>
"""


# ------------------------------------------------------------------ main

def main() -> None:
    weeks = fetch_calendar()
    upstream = fetch_upstream()
    # keep the proof visible: 3 most recent upstream merges mixed in with 6 recent commits
    events = sorted(upstream[:3] + fetch_commits()[:6], key=lambda e: e["date"], reverse=True)
    s = stats(weeks, upstream)
    for name, t in THEMES.items():
        d = OUT / name
        d.mkdir(parents=True, exist_ok=True)
        (d / "hero.svg").write_text(hero(t))
        (d / "radar.svg").write_text(radar(weeks, s, t))
        (d / "feed.svg").write_text(feed(events, t))
        for i, p in enumerate(PROJECTS):
            (d / f"card-{p['name'].lower()}.svg").write_text(card(p, i, t))
    print(f"wrote {len(THEMES)} themes; {s['total']} contributions, {len(events)} feed rows")


if __name__ == "__main__":
    main()
