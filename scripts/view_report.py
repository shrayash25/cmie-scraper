#!/usr/bin/env python3
"""
Render CMIE pipe-delimited report .txt files as good-looking HTML tables and
open them in the browser.

The raw files look cryptic (Year|Frequency|metric|metric|...). This pivots them
into the analyst-friendly layout (indicators down the side, time periods across
the top), formats periods and numbers, and attaches source provenance.

Usage:
  python view_report.py data/A_183350.txt        # one file -> open it
  python view_report.py                            # all of data/ -> index page
  python view_report.py data/ --no-open            # render only, don't launch browser
"""
from __future__ import annotations

import argparse
import datetime as dt
import html
import json
import pathlib
import subprocess
import sys

import cmie_common as cc

VIEW_DIR = cc.VIEW_DIR
RAW_DIR = cc.RAW_DIR

CSS = """
:root{--bg:#f6f7f9;--card:#fff;--ink:#1f2933;--mut:#6b7280;--line:#e5e7eb;
--head:#0f2740;--head2:#1e3a5f;--zebra:#f9fafb;--hover:#eef6ff;--neg:#c0392b;--accent:#2563eb;}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);
font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;
font-size:14px;line-height:1.45;padding:28px;}
.wrap{max-width:1280px;margin:0 auto;}
.card{background:var(--card);border:1px solid var(--line);border-radius:14px;
box-shadow:0 1px 3px rgba(0,0,0,.06),0 8px 24px rgba(0,0,0,.04);overflow:hidden;margin-bottom:26px;}
.cap{padding:18px 22px;border-bottom:1px solid var(--line);}
.cap h1{margin:0 0 4px;font-size:18px;font-weight:700;letter-spacing:-.01em;}
.cap .sub{color:var(--mut);font-size:13px;}
.badges{margin-top:10px;display:flex;gap:8px;flex-wrap:wrap;}
.badge{font-size:12px;padding:3px 10px;border-radius:999px;background:#eef2ff;color:#3730a3;font-weight:600;}
.badge.unit{background:#ecfdf5;color:#065f46;}
.badge.freq{background:#fef3c7;color:#92400e;}
.scroll{overflow:auto;max-height:78vh;}
table{border-collapse:separate;border-spacing:0;width:100%;font-variant-numeric:tabular-nums;}
th,td{padding:7px 12px;border-bottom:1px solid var(--line);white-space:nowrap;font-size:13px;}
thead th{position:sticky;top:0;background:var(--head);color:#fff;text-align:right;font-weight:600;z-index:2;}
thead th:first-child{text-align:left;left:0;z-index:3;background:var(--head2);min-width:280px;}
tbody th{position:sticky;left:0;background:var(--card);text-align:left;font-weight:500;z-index:1;
max-width:380px;overflow:hidden;text-overflow:ellipsis;}
tbody td{text-align:right;}
tbody tr:nth-child(even) th,tbody tr:nth-child(even) td{background:var(--zebra);}
tbody tr:hover th,tbody tr:hover td{background:var(--hover);}
td.neg{color:var(--neg);}
td.blank{color:#cbd5e1;text-align:center;}
tr.count th,tr.count td{border-top:2px solid var(--head);font-style:italic;color:var(--mut);background:#fff;}
.foot{padding:12px 22px;border-top:1px solid var(--line);color:var(--mut);font-size:12px;
font-family:ui-monospace,SFMono-Regular,Menlo,monospace;word-break:break-all;}
a{color:var(--accent);text-decoration:none;} a:hover{text-decoration:underline;}
.idx li{margin:6px 0;} .idx .u{color:var(--mut);font-size:12px;}
"""


def fmt_period(raw: str, freq: str) -> str:
    s = raw.strip()
    if len(s) != 8 or not s.isdigit():
        return html.escape(s)
    y, m = int(s[:4]), int(s[4:6])
    if freq == "A":
        return f"{y-1}-{str(y)[2:]}" if m == 3 else str(y)   # fiscal year ending Mar
    if freq == "M":
        return f"{y}-{m:02d}"
    if freq == "Q":
        return f"{y} Q{(m - 1)//3 + 1}"
    if freq == "HY":
        return f"{y} H{1 if m <= 6 else 2}"
    return f"{y}-{m:02d}-{s[6:8]}"


def fmt_num(v: str) -> str:
    v = v.strip()
    if v == "":
        return '<td class="blank">–</td>'
    try:
        f = float(v.replace(",", ""))
    except ValueError:
        return f"<td>{html.escape(v)}</td>"
    cls = " class='neg'" if f < 0 else ""
    return f"<td{cls}>{html.escape(v)}</td>"


def parse_cmie_txt(path: pathlib.Path) -> dict:
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    title_parts = [p.strip() for p in lines[0].split(" : ")]
    table = title_parts[0] if title_parts else path.stem
    unit = title_parts[-1] if len(title_parts) > 1 else ""
    industry = " : ".join(title_parts[1:-1]) if len(title_parts) > 2 else ""
    header = lines[1].split("|") if len(lines) > 1 else []
    data = [ln.split("|") for ln in lines[2:] if any(c.strip() for c in ln.split("|"))]
    freq = data[0][1].strip() if data and len(data[0]) > 1 else ""
    return {"table": table, "industry": industry, "unit": unit,
            "header": header, "data": data, "freq": freq, "path": path}


def load_provenance(path: pathlib.Path) -> dict | None:
    meta = RAW_DIR / f"{path.stem}.meta.json"
    if meta.exists():
        try:
            return json.loads(meta.read_text())
        except Exception:
            return None
    return None


def render_table_html(p: dict) -> str:
    header, data, freq = p["header"], p["data"], p["freq"]
    # columns 0=Year, 1=Frequency, 2..=metrics (last is usually Count)
    metric_idx = list(range(2, len(header)))
    periods = [fmt_period(row[0], freq) for row in data]

    thead = "<tr><th>Indicator</th>" + "".join(f"<th>{html.escape(pd)}</th>" for pd in periods) + "</tr>"

    body_rows = []
    for j in metric_idx:
        name = header[j].strip() if j < len(header) else f"col{j}"
        is_count = name.lower() == "count"
        cells = "".join(fmt_num(row[j] if j < len(row) else "") for row in data)
        tr_cls = " class='count'" if is_count else ""
        body_rows.append(f"<tr{tr_cls}><th>{html.escape(name)}</th>{cells}</tr>")

    prov = load_provenance(p["path"])
    foot = ""
    if prov:
        foot = (f"<div class='foot'>Source: {html.escape(prov.get('request_url',''))}<br>"
                f"fetched {html.escape(prov.get('fetched_at_utc',''))} · "
                f"sha256 {html.escape(prov.get('sha256','')[:16])}… · file {html.escape(p['path'].name)}</div>")

    badges = f"<span class='badge unit'>{html.escape(p['unit'])}</span>" if p["unit"] else ""
    if freq:
        fl = {"A": "Annual", "M": "Monthly", "Q": "Quarterly", "HY": "Half-yearly", "W": "Weekly", "D": "Daily"}.get(freq, freq)
        badges += f"<span class='badge freq'>{fl}</span>"
    if periods:
        badges += f"<span class='badge'>{html.escape(periods[0])} – {html.escape(periods[-1])}</span>"

    return f"""<div class="card">
  <div class="cap"><h1>{html.escape(p['table'])}</h1>
    <div class="sub">{html.escape(p['industry'])}</div>
    <div class="badges">{badges}</div></div>
  <div class="scroll"><table><thead>{thead}</thead><tbody>{''.join(body_rows)}</tbody></table></div>
  {foot}
</div>"""


def page(title: str, inner: str) -> str:
    return (f"<!doctype html><html lang='en'><head><meta charset='utf-8'>"
            f"<meta name='viewport' content='width=device-width,initial-scale=1'>"
            f"<title>{html.escape(title)}</title><style>{CSS}</style></head>"
            f"<body><div class='wrap'>{inner}</div></body></html>")


def open_in_browser(path: pathlib.Path):
    url = path.resolve().as_uri()
    try:
        if sys.platform == "darwin":
            subprocess.run(["open", url], check=False)
        else:
            import webbrowser
            webbrowser.open(url)
    except Exception as e:
        print(f"(could not auto-open: {e})  Open manually: {url}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("target", nargs="?", default=str(cc.DATA_DIR),
                    help="a .txt file or a directory (default: data/parsed/)")
    ap.add_argument("--no-open", action="store_true")
    args = ap.parse_args()

    VIEW_DIR.mkdir(exist_ok=True)
    target = pathlib.Path(args.target)

    if target.is_file():
        p = parse_cmie_txt(target)
        out = VIEW_DIR / f"{target.stem}.html"
        out.write_text(page(p["table"], render_table_html(p)))
        print(f"rendered -> {out}")
        if not args.no_open:
            open_in_browser(out)
        return 0

    files = sorted(target.glob("*.txt"))
    if not files:
        sys.exit(f"No .txt files in {target}")
    items = []
    for f in files:
        p = parse_cmie_txt(f)
        out = VIEW_DIR / f"{f.stem}.html"
        out.write_text(page(p["table"], render_table_html(p)))
        items.append(f"<li><a href='{out.name}'>{html.escape(p['table'])}</a> "
                     f"<span class='u'>· {html.escape(p['industry'])} · {html.escape(p['unit'])}</span></li>")
    index = VIEW_DIR / "index.html"
    index.write_text(page("CMIE reports", f"<div class='card'><div class='cap'>"
                          f"<h1>CMIE Reports — {len(files)} tables</h1>"
                          f"<div class='sub'>Asset Management Services (Mutual Funds)</div></div>"
                          f"<div style='padding:14px 22px'><ul class='idx'>{''.join(items)}</ul></div></div>"))
    print(f"rendered {len(files)} tables -> {index}")
    if not args.no_open:
        open_in_browser(index)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
