#!/usr/bin/env python3
"""
Enumerate every downloadable report table for a CMIE industry (icode).

Walks each report-category tab (kall=wshowtab&icode=..&tabno=..), parses the
table rows, and extracts (tabno, tab_label, title, repnum, frequency, repcode).
Writes a catalog CSV so we know exactly what to download.

Polite: jittered delay between page fetches. Reuses the session cookie from
capture_curl.txt.

Usage:
  python enumerate_reports.py --icode 0102280500000000 [--out report_catalog.csv]
"""
from __future__ import annotations

import argparse
import csv
import random
import re
import time

import cmie_common as cc


def fetch(session, icode: str, tabno: str) -> str:
    r = session.get(cc.BASE, params={"kall": "wshowtab", "icode": icode, "tabno": tabno}, timeout=60)
    r.raise_for_status()
    cc.TAB_CACHE.mkdir(parents=True, exist_ok=True)
    (cc.TAB_CACHE / f"{icode}_{tabno}.html").write_text(r.text, errors="replace")
    return r.text


def discover_tabs(html: str):
    """Return {tabno: label} for the report-category tab bar."""
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "html.parser")
    tabs = {}
    for a in soup.find_all("a", href=True):
        if "wshowtab" not in a["href"]:
            continue
        m = re.search(r"tabno=([0-9]+)", a["href"])
        label = a.get_text(strip=True)
        # skip the industry-tree links (they reuse tabno=0001 with industry names)
        if m and label and "icode=0102" not in a["href"][:0]:
            tabs.setdefault(m.group(1), label)
    return tabs


def parse_tables(html: str, tabno: str, tab_label: str):
    """Yield dict rows: one per (table title x frequency link)."""
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "html.parser")
    rows = []
    for title_td in soup.select("td.l_table"):
        title = title_td.get_text(strip=True)
        if not title:
            continue
        tr = title_td.find_parent("tr")
        if not tr:
            continue
        for a in tr.find_all("a", href=True):
            href = a["href"]
            rep = re.search(r"repnum=([0-9]+)", href)
            if not rep:
                continue
            freq = re.search(r"frequency=([A-Za-z]+)", href)
            code = re.search(r"repcode=([0-9]+)", href)
            rows.append({
                "tabno": tabno, "tab_label": tab_label, "title": title,
                "repnum": rep.group(1),
                "frequency": freq.group(1) if freq else "",
                "freq_label": a.get_text(strip=True),
                "repcode": code.group(1) if code else "",
            })
    return rows


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--icode", required=True)
    ap.add_argument("--out", default=str(cc.CATALOG))
    ap.add_argument("--min-delay", type=float, default=1.5)
    ap.add_argument("--max-delay", type=float, default=3.5)
    args = ap.parse_args()

    import pathlib
    import requests
    pathlib.Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    session = requests.Session()
    session.headers.update(cc.load_session_headers())

    # 1) discover the report-category tabs from the default tab page
    first = fetch(session, args.icode, "0001")
    tabs = discover_tabs(first)
    print(f"discovered tabs: {tabs}")

    all_rows = []
    for tabno, label in sorted(tabs.items()):
        time.sleep(random.uniform(args.min_delay, args.max_delay))  # polite
        try:
            html = fetch(session, args.icode, tabno)
        except Exception as e:
            print(f"  tab {tabno} ({label}): FETCH ERROR {e}")
            continue
        rows = parse_tables(html, tabno, label)
        print(f"  tab {tabno} ({label}): {len(rows)} table/freq entries, "
              f"{len({r['repnum'] for r in rows})} distinct repnums")
        all_rows.extend(rows)

    # dedupe by (repnum, frequency)
    seen, deduped = set(), []
    for r in all_rows:
        key = (r["repnum"], r["frequency"])
        if key not in seen:
            seen.add(key)
            deduped.append(r)

    with open(args.out, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["tabno", "tab_label", "title", "repnum", "frequency", "freq_label", "repcode"])
        w.writeheader()
        w.writerows(deduped)

    titles = {r["title"] for r in deduped}
    print(f"\nCatalog: {len(deduped)} downloadable (table x frequency) entries, "
          f"{len(titles)} distinct tables -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
