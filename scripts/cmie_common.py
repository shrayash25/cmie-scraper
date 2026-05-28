"""
Shared CMIE download helpers: session auth, the wrddmp dump request, and
saving each download with full source provenance.

Auth model: the site is effectively IP-authorized (MyLOFT presents an approved
IP); the session cookie just tracks the session. We read that cookie from
capture_curl.txt (Copy as cURL) or the CMIE_COOKIE env var.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import io
import json
import os
import pathlib
import re
import time
import zipfile

BASE = "https://industryoutlook.cmie.com/kommon/bin/sr.php"

# All paths resolve relative to the project root (the parent of scripts/), so
# the tools work no matter which directory you run them from.
ROOT = pathlib.Path(__file__).resolve().parent.parent
CURL_FILE = ROOT / "capture_curl.txt"          # session cookie (Copy as cURL); SENSITIVE
DATA_DIR = ROOT / "data" / "parsed"            # extracted pipe-delimited .txt files
RAW_DIR = ROOT / "data" / "raw"                # immutable raw zips + provenance sidecars
CATALOG = ROOT / "data" / "catalog" / "report_catalog.csv"
TAB_CACHE = ROOT / "data" / "tab_pages"        # cached wshowtab HTML (enumeration source)
VIEW_DIR = ROOT / "output" / "view"            # generated HTML tables
LOG_DIR = ROOT / "logs"
COMPLETED = LOG_DIR / "completed_reports.log"  # resume log
ERRORS = LOG_DIR / "errors.log"

VALID_FREQ = {"A", "M", "Q", "HY", "W", "D"}


def load_session_headers() -> dict:
    """Cookie (+ User-Agent) from CMIE_COOKIE env or capture_curl.txt."""
    cookie = os.environ.get("CMIE_COOKIE")
    ua = os.environ.get("CMIE_UA")
    if CURL_FILE.exists():
        text = CURL_FILE.read_text(errors="replace")
        if not cookie:
            m = re.search(r"-b\s+'(.*?)'", text) or re.search(r"(?i)-H\s+'cookie:\s*(.*?)'", text)
            cookie = m.group(1) if m else None
        if not ua:
            m = re.search(r"(?i)-H\s+'user-agent:\s*(.*?)'", text)
            ua = m.group(1) if m else None
    if not cookie:
        raise SystemExit("No session cookie (set CMIE_COOKIE or save capture_curl.txt).")
    return {"Cookie": cookie, "User-Agent": ua or "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"}


def looks_like_login_page(body: bytes) -> bool:
    head = body[:4096].lower()
    return (b"<html" in head) and (b"login" in head or b"password" in head or b"whpage" in head)


def download_dump(session, repnum: str, frequency: str = "A", colno: str = "1"):
    """GET the wrddmp dump for one report. Returns the requests.Response."""
    params = {
        "kall": "wrddmp", "type": "dmp", "tabcode": "",
        "frequency": frequency, "colno": colno, "repnum": str(repnum), "dnbtn": "1",
    }
    return session.get(BASE, params=params, headers=session.headers, timeout=60)


def fetch_dump_ready(session, repnum: str, frequency: str = "A", colno: str = "1",
                     max_wait: float = 120, poll: float = 6):
    """Request the dump, polling through the async 'download has commenced /
    please wait' page until the ZIP is ready. Returns the Response holding the zip.

    Raises RuntimeError on a dead session, TimeoutError if not ready in time.
    """
    deadline = time.time() + max_wait
    while True:
        resp = download_dump(session, repnum, frequency, colno)
        body = resp.content
        if body[:4] == b"PK\x03\x04":          # zip => data is ready
            return resp
        if looks_like_login_page(body):
            raise RuntimeError("session dead (login page returned)")
        if time.time() >= deadline:
            raise TimeoutError(f"dump for repnum {repnum} not ready after {max_wait}s")
        time.sleep(poll)                        # still generating; wait and retry


def save_dump(repnum: str, frequency: str, resp) -> dict:
    """Persist raw bytes + extracted txt + provenance sidecar. Returns provenance."""
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    body = resp.content
    sha = hashlib.sha256(body).hexdigest()
    is_zip = body[:4] == b"PK\x03\x04"
    stem = f"{frequency}_{repnum}"

    (RAW_DIR / f"{stem}{'.zip' if is_zip else '.bin'}").write_bytes(body)
    extracted = []
    if is_zip:
        with zipfile.ZipFile(io.BytesIO(body)) as z:
            for name in z.namelist():
                out = DATA_DIR / pathlib.Path(name).name
                out.write_bytes(z.read(name))
                extracted.append(str(out))
    else:
        out = DATA_DIR / f"{stem}.txt"
        out.write_bytes(body)
        extracted.append(str(out))

    prov = {
        "request_url": resp.url,
        "repnum": str(repnum), "frequency": frequency,
        "fetched_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "http_status": resp.status_code,
        "content_type": resp.headers.get("Content-Type"),
        "content_disposition": resp.headers.get("Content-Disposition"),
        "sha256": sha, "n_bytes": len(body), "extracted": extracted,
    }
    (RAW_DIR / f"{stem}.meta.json").write_text(json.dumps(prov, indent=2))
    return prov
