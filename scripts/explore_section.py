#!/usr/bin/env python3
"""
Fetch one authenticated CMIE page and enumerate the report links on it
(repnum / repcode / icode), so we can discover every table in a section.

Reuses the session cookie from capture_curl.txt.

Usage:
  python explore_section.py "<url>"
  # defaults to the Asset Management Services (Mutual Funds) section page.
"""
from __future__ import annotations

import re
import sys
from collections import Counter
from urllib.parse import parse_qs, urlparse

import cmie_common as cc

DEBUG = cc.ROOT / "output" / "scratch"

# The section page the user was on (from the captured Referer).
DEFAULT_URL = (
    "https://industryoutlook.cmie.com/kommon/bin/sr.php"
    "?type=dmp&kall=wrddmp&repcode=505005005000000000000000000000000000000000000"
    "&repnum=183350&frequency=A&icode=0102280500000000"
)


def main() -> int:
    url = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_URL
    import requests
    from bs4 import BeautifulSoup

    r = requests.get(url, headers=cc.load_session_headers(), timeout=60)
    print(f"HTTP {r.status_code} | {len(r.content)} bytes | {r.headers.get('Content-Type')}")
    DEBUG.mkdir(parents=True, exist_ok=True)
    (DEBUG / "section_page.html").write_text(r.text, errors="replace")
    print(f"saved raw HTML -> {DEBUG/'section_page.html'}\n")

    html = r.text
    # 1) Anchor links that carry report params
    print("=== <a> links with repnum/repcode/icode ===")
    soup = BeautifulSoup(html, "html.parser")
    seen = set()
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if any(k in href for k in ("repnum", "repcode", "icode")):
            if href in seen:
                continue
            seen.add(href)
            q = parse_qs(urlparse(href).query)
            print(f"  {a.get_text(strip=True)!r:55} repnum={q.get('repnum')} repcode={q.get('repcode')}")
    if not seen:
        print("  (none found in <a> hrefs — links may be built by JS; see regex scan)\n")

    # 2) Raw regex scan (catches JS-built links / onclick / forms)
    print("\n=== distinct repnum values in raw HTML (with counts) ===")
    for val, n in Counter(re.findall(r"repnum=(\d+)", html)).most_common():
        print(f"  repnum={val}  (x{n})")
    print("\n=== distinct repcode values ===")
    for val, n in Counter(re.findall(r"repcode=([0-9]{6,})", html)).most_common():
        print(f"  repcode={val}  (x{n})")
    print("\n=== distinct icode values ===")
    for val, n in Counter(re.findall(r"icode=([0-9]{6,})", html)).most_common():
        print(f"  icode={val}  (x{n})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
