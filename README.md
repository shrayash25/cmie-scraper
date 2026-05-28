# CMIE Industry Outlook — Offline Replica

Build a local, queryable copy of [CMIE Industry Outlook](https://industryoutlook.cmie.com) time-series data, with **every value traceable to its exact source** (download URL + parameters + fetch timestamp + content hash). The pipeline is validated end-to-end on one industry (Asset Management Services / Mutual Funds) and ready to scale to all 210 industries.

> **New here?** Read this file top to bottom — it's the full guided tour.

---

## Prerequisites

- **Python 3.10+** (developed on 3.13)
- **An active CMIE Industry Outlook subscription**, and a way to reach the site from an IP CMIE has whitelisted for you. We use **MyLOFT** (an institutional remote-access browser extension); any whitelisted IP works.
- macOS or Linux. Tested on macOS.

## Quick start (10 minutes from clone to a viewable HTML table)

```bash
git clone <this-repo> cmie_scraper
cd cmie_scraper

# Set up the virtualenv and install deps
python3 -m venv venv
./venv/bin/pip install -q requests beautifulsoup4 openpyxl

# 1. Capture your authenticated session  (see "Authentication" below)
#    Save the result as ./capture_curl.txt   (git-ignored)

# 2. Enumerate one industry's catalog of tables
./venv/bin/python scripts/enumerate_reports.py --icode 0102280500000000   # AMS Mutual Funds

# 3. Download a small validation batch (10 Annual-frequency tables)
./venv/bin/python scripts/download_batch.py --tab "Annual Financials" --freq A --limit 10

# 4. View the results as HTML in your browser
./venv/bin/python scripts/view_report.py

# 5. Consolidate everything into shareable datasets (long CSV + Excel workbook)
./venv/bin/python scripts/build_dataset.py
```

After step 4 your browser should open `output/view/index.html` with the 10 tables nicely rendered. After step 5 you'll have `output/share/cmie_dataset_long.csv` and `cmie_dataset.xlsx`.

---

## Authentication — getting `capture_curl.txt`

CMIE is **IP-authorized**: the site recognizes whitelisted IPs (directly or via a remote-access proxy like MyLOFT) and serves data without a username/password — a session cookie just tracks the session. So the scripts simply ride your already-authenticated browser session.

1. In your normal browser (with MyLOFT or your access route configured), open CMIE Industry Outlook and navigate to any industry → any data table.
2. Click that table's **Download** button. In DevTools → **Network**, find the request whose URL contains `sr.php?kall=wrddmp`.
3. Right-click it → **Copy → Copy as cURL**.
4. Paste the result into a file named **`capture_curl.txt`** in the project root.

The scripts auto-extract `Cookie` and `User-Agent` from that cURL. **The cookie expires periodically** — when downloads start returning login pages, the batch downloader stops loudly; recapture and re-run. It picks up where it left off via `logs/completed_reports.log`.

> ⚠️ `capture_curl.txt` holds a live session cookie. **Git-ignored on purpose** — never commit it.

---

## How it works — the mental model

The site addresses data through a four-level hierarchy:

```
industry (icode) ──▶ report category (tabno) ──▶ table ──▶ download (repnum)
```

- **`kall=wshowtab&icode=<I>&tabno=<T>`** renders the report-category page; each table's `repnum` is embedded in the HTML (no JavaScript execution required to read it).
- **`kall=wrddmp&...&repnum=<N>&frequency=<F>&dnbtn=1`** downloads one table as a ZIP containing a clean pipe-delimited `.txt`:
  - line 1 — `Table : Industry : Unit`
  - line 2 — `Year | Frequency | metric₁ | metric₂ | … | Count`
  - then one row per period (`YYYYMMDD` date format)

### The one async gotcha — do not skip

A fresh download request first returns a *"download has commenced — please wait"* HTML page (with a 20-second auto-refresh). The real ZIP only arrives once the server finishes generating it. The downloader **polls** the same URL until it gets a ZIP. Missing this silently saves the "please wait" page as if it were data — that bug is caught and fixed; just be aware if you're modifying the download code.

---

## Repository tour

```
scripts/                  the pipeline — all run from project root
  cmie_common.py            shared: path config, auth, async-polling download, save + provenance
  enumerate_reports.py      icode → catalog of an industry's tables
  download_batch.py         catalog → bulk downloads (polite, resume-able, stops on dead session)
  download_report.py        download a single report (tester)
  view_report.py            render the .txt files as clean HTML tables
  build_dataset.py          consolidate downloads → long CSV + multi-sheet Excel workbook
  explore_section.py        dev utility: inspect any authenticated page

reference/
  file-structure.yaml       CMIE industry taxonomy (handy when scaling)

README.md                   this file
capture_curl.txt            YOUR session cookie  (git-ignored; create as described above)
.gitignore
```

These directories are generated locally and **git-ignored** (they hold subscription data or are easily re-runnable):

```
data/      catalog/ + raw/ (zips + provenance) + parsed/ (.txt files) + tab_pages/ (cache)
output/    view/ (HTML tables) + share/ (long CSV + Excel workbook)
logs/      completed_reports.log + errors.log
trash/     superseded / redundant files, safe to delete
venv/      Python virtualenv
```

---

## The pipeline at a glance

| Step | Script | Input | Output |
| --- | --- | --- | --- |
| 1 | `enumerate_reports.py --icode <I>` | one `icode` | `data/catalog/report_catalog.csv` |
| 2 | `download_batch.py [--tab ...] [--freq ...] [--limit N]` | the catalog | `data/raw/*.zip` + `data/parsed/*.txt` + provenance sidecars + `logs/completed_reports.log` |
| 3 | `view_report.py` | parsed files | `output/view/*.html` (with `index.html`) |
| 4 | `build_dataset.py` | parsed files + catalog + provenance | `output/share/cmie_dataset_long.csv` + `cmie_dataset.xlsx` |

Each step is **idempotent**: re-runs don't duplicate work. `download_batch.py` uses `logs/completed_reports.log` to skip already-fetched tables; the others overwrite their outputs.

### Useful invocations

```bash
# Big runs: launch in the background and tail the log
nohup ./venv/bin/python scripts/download_batch.py > logs/run.log 2>&1 &
tail -f logs/completed_reports.log

# After a cookie refresh, just re-run the same command — already-done work is skipped
./venv/bin/python scripts/download_batch.py --tab "Annual Financials"
```

---

## Status

- ✅ Auth confirmed, navigation reverse-engineered, polite resume-able downloader, async-polling fixed, HTML viewer, dataset consolidation (long CSV + Excel workbook).
- ✅ **Asset Management Services (Mutual Funds)** — fully cataloged (155 tables / 688 table×freq targets across 5 categories) and **Annual Financials downloaded (67/68)** as the working reference. Reproduce locally by running the quick start above.
- ⏳ **Next:** scale to the other 4 categories, then to all 210 industries (the `icode` scheme generalizes); retry the 1 failed table (`repnum 210064 "Company-wise"`, needs a longer timeout); design the PostgreSQL load.

---

## Important notes for contributors

- **Don't commit subscription data.** `data/`, `output/`, and the source-artifact reference files (`reference/ias_indicator.*`, `reference/Tdx_addin.xlam`, `reference/samples/`) are git-ignored intentionally. CMIE content is paid; each subscriber generates their own copy locally.
- **Traceability is non-negotiable.** Every downloaded value can be re-derived from the raw ZIP saved in `data/raw/` and its `.meta.json` sidecar (source URL, params, fetch timestamp UTC, SHA-256). Keep this property when you change the parsers.
- **Be polite.** Jittered delays (1.5–3.5 s) between requests and async polling are not optional; CMIE is a small subscription provider, and the IP can be blocked.
