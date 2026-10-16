#!/usr/bin/env python3
"""Refresh the 'merged upstream' list in README.md from GitHub's search API.

Rewrites everything between <!--UPSTREAM:START--> and <!--UPSTREAM:END-->.
Uses only the standard library; GITHUB_TOKEN is optional (raises rate limits).
"""
import json
import os
import re
import urllib.parse
import urllib.request
from pathlib import Path

USER = "tejgokani"
# Repos to leave out: my own, plus team/course repos where the PRs are internal.
EXCLUDE = {"harxhe/kernel-module-rootkit-detector"}
LIMIT = 8
README = Path(__file__).resolve().parent.parent / "README.md"


def fetch() -> list[dict]:
    q = f"author:{USER} is:pr is:merged -user:{USER}"
    url = "https://api.github.com/search/issues?" + urllib.parse.urlencode(
        {"q": q, "sort": "updated", "order": "desc", "per_page": 50}
    )
    req = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json"})
    if token := os.environ.get("GITHUB_TOKEN"):
        req.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)["items"]


def render(items: list[dict]) -> str:
    rows, seen = [], 0
    for it in items:
        repo = it["repository_url"].split("/repos/")[1]
        if repo in EXCLUDE:
            continue
        title = it["title"].replace("|", "\\|")
        merged = (it.get("pull_request", {}).get("merged_at") or it["closed_at"])[:10]
        rows.append(f"| [`{repo}`](https://github.com/{repo}) | [{title}]({it['html_url']}) | {merged} |")
        seen += 1
        if seen == LIMIT:
            break
    head = "| Project | Fix | Merged |\n|:--|:--|:--|"
    return head + "\n" + "\n".join(rows)


def main() -> None:
    table = render(fetch())
    text = README.read_text()
    new = re.sub(
        r"(<!--UPSTREAM:START-->).*?(<!--UPSTREAM:END-->)",
        lambda m: f"{m.group(1)}\n{table}\n{m.group(2)}",
        text,
        flags=re.S,
    )
    if new != text:
        README.write_text(new)
        print("README updated")
    else:
        print("no change")


if __name__ == "__main__":
    main()
