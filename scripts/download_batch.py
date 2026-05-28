#!/usr/bin/env python3
"""
Batch-download CMIE reports listed in report_catalog.csv.

Polite (jittered delays), resume-able (skips entries already in
completed_reports.log), and fails loudly if the session dies (login page).
Each download is saved with full provenance via cmie_common.save_dump.

Examples:
  # validation batch: 10 Annual-frequency tables from Annual Financials
  python download_batch.py --tab "Annual Financials" --freq A --limit 10

  # everything in the catalog
  python download_batch.py
"""
from __future__ import annotations

import argparse
import csv
import random
import sys
import time

import cmie_common as cc

CATALOG = cc.CATALOG
COMPLETED = cc.COMPLETED
ERRORS = cc.ERRORS


def load_catalog(tab: str | None, freq: str | None, limit: int | None):
    rows = list(csv.DictReader(open(CATALOG)))
    out = []
    for r in rows:
        if r["frequency"] not in cc.VALID_FREQ:
            continue  # skip the malformed-frequency edge rows
        if tab and r["tab_label"] != tab:
            continue
        if freq and r["frequency"] != freq:
            continue
        out.append(r)
    return out[:limit] if limit else out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tab", help="filter by tab_label, e.g. 'Annual Financials'")
    ap.add_argument("--freq", help="filter by frequency code, e.g. A")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--min-delay", type=float, default=1.5)
    ap.add_argument("--max-delay", type=float, default=3.5)
    args = ap.parse_args()

    import requests

    cc.LOG_DIR.mkdir(parents=True, exist_ok=True)
    targets = load_catalog(args.tab, args.freq, args.limit)
    done = set(COMPLETED.read_text().split()) if COMPLETED.exists() else set()
    print(f"{len(targets)} target(s); {len(done)} already completed (will skip).")

    session = requests.Session()
    session.headers.update(cc.load_session_headers())

    ok = skipped = failed = 0
    for i, r in enumerate(targets, 1):
        key = f"{r['frequency']}_{r['repnum']}"
        if key in done:
            skipped += 1
            continue
        try:
            resp = cc.fetch_dump_ready(session, r["repnum"], r["frequency"])
            prov = cc.save_dump(r["repnum"], r["frequency"], resp)
            with COMPLETED.open("a") as f:
                f.write(key + "\n")
            ok += 1
            print(f"  [{i}/{len(targets)}] OK {key} | {r['title'][:45]:45} | {prov['n_bytes']}B")
        except RuntimeError as e:
            if "session dead" in str(e):
                sys.exit(f"\nSESSION DEAD at {key} ({r['title']!r}): {e}\n"
                         f"Re-capture capture_curl.txt and re-run; completed work is skipped.")
            failed += 1
            with ERRORS.open("a") as f:
                f.write(f"{key}\t{r['title']}\t{e}\n")
            print(f"  [{i}/{len(targets)}] FAIL {key} | {e}")
        except Exception as e:
            failed += 1
            with ERRORS.open("a") as f:
                f.write(f"{key}\t{r['title']}\t{e}\n")
            print(f"  [{i}/{len(targets)}] FAIL {key} | {e}")
        time.sleep(random.uniform(args.min_delay, args.max_delay))  # polite

    print(f"\nDone. ok={ok} skipped={skipped} failed={failed}. "
          f"Parsed txt in {cc.DATA_DIR} ; raw+provenance in {cc.RAW_DIR} ; log: {COMPLETED}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
