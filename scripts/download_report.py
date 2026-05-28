#!/usr/bin/env python3
"""
Download ONE CMIE report (table) by repnum — a quick tester / one-off fetch.

Uses the shared logic in cmie_common (polls through the async "please wait"
page, saves the raw zip + extracted txt + provenance sidecar). For bulk
downloads use download_batch.py instead.

Session: reads your cookie from capture_curl.txt (Copy as cURL) or CMIE_COOKIE.

Run (with venv active):
  python scripts/download_report.py --repnum 183350 --freq A
"""
from __future__ import annotations

import argparse
import json

import cmie_common as cc


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--repnum", required=True, help="report number (from report_catalog.csv)")
    ap.add_argument("--freq", default="A", help="frequency code: A/M/Q/HY/W/D (default A)")
    ap.add_argument("--colno", default="1")
    args = ap.parse_args()

    import requests
    session = requests.Session()
    session.headers.update(cc.load_session_headers())

    resp = cc.fetch_dump_ready(session, args.repnum, args.freq, args.colno)
    prov = cc.save_dump(args.repnum, args.freq, resp)
    print(json.dumps(prov, indent=2))
    print("\nSaved:", *prov["extracted"], sep="\n  ")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
