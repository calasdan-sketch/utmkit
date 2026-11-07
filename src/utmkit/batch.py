"""Batch processing: campaign spec CSV -> tracked links, slugs, optional QR + HTML."""
from __future__ import annotations

import csv
import difflib
import html
import os
import re
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from .channels import ga4_channel
from .core import (Campaign, Finding, build_url, sanitize, slugify,
                   validate_campaign, validate_rows)
from .taxonomy import Taxonomy, check_taxonomy, fix_campaign
from .qr import Backend, QrUnavailable, get_backend

COLUMNS = ("url", "source", "medium", "campaign", "term", "content", "name",
           "id", "source_platform", "creative_format", "marketing_tactic")
MAX_ROWS = 200_000
_ALIASES = {
    "landing_page": "url", "destination": "url", "link": "url", "target_url": "url",
    "utm_source": "source", "utm_medium": "medium", "utm_campaign": "campaign",
    "utm_term": "term", "utm_content": "content", "utm_id": "id", "campaign_id": "id",
    "utm_source_platform": "source_platform", "utm_creative_format": "creative_format",
    "utm_marketing_tactic": "marketing_tactic", "campaign_name": "campaign",
    "keyword": "term", "label": "name",
}


def _canon_header(h: str) -> str:
    h = re.sub(r"[\s\-]+", "_", (h or "").strip().lower())
    return _ALIASES.get(h, h)


def load_spec(path: str) -> Tuple[List[tuple], List[Finding]]:
    """Read the spec CSV; returns ([(row_number, Campaign)], findings about the file itself).

    Accepts comma or semicolon delimiters (Excel in many locales), a BOM, and
    header aliases such as ``utm_source`` or ``Landing Page``. Unknown columns
    are reported (with a did-you-mean) instead of silently ignored.
    """
    findings: List[Finding] = []
    out: List[tuple] = []
    try:
        with open(path, newline="", encoding="utf-8-sig") as fh:
            head = fh.readline()
            delim = ";" if head.count(";") > head.count(",") else ","
            fh.seek(0)
            reader = csv.reader(fh, delimiter=delim)
            try:
                header = next(reader)
            except StopIteration:
                raise ValueError("spec CSV is empty") from None
            names = [_canon_header(h) for h in header]
            if "url" not in names:
                raise ValueError("spec CSV needs a 'url' column")
            seen = set()
            for n, raw in zip(names, header):
                if n in seen and n:
                    raise ValueError(f"spec CSV has two columns meaning {n!r}")
                seen.add(n)
                if n and n not in COLUMNS:
                    guess = difflib.get_close_matches(n, COLUMNS, n=1)
                    findings.append(Finding(
                        "warn", "unknown_column", "header",
                        f"column {sanitize(raw)!r} is ignored"
                        + (f" (did you mean {guess[0]!r}?)" if guess else "")))
            for i, row in enumerate(reader, start=2):
                if not any(c.strip() for c in row):
                    continue
                if len(out) >= MAX_ROWS:
                    raise ValueError(f"spec CSV has more than {MAX_ROWS} rows")
                norm = {names[k]: v.strip() for k, v in enumerate(row[:len(names)])}
                out.append((i, Campaign(**{c: norm.get(c, "") for c in COLUMNS})))
    except csv.Error as e:
        raise ValueError(f"spec CSV is malformed: {e}") from None
    except UnicodeDecodeError:
        raise ValueError("spec CSV is not valid UTF-8 (re-save it as 'CSV UTF-8')") from None
    return out, findings


def load_campaigns(path: str) -> List[tuple]:
    """Read the spec CSV; returns [(row_number, Campaign)] (see :func:`load_spec`)."""
    return load_spec(path)[0]


@dataclass
class BatchResult:
    rows: List[dict] = field(default_factory=list)
    findings: List[Finding] = field(default_factory=list)
    qr_written: List[str] = field(default_factory=list)


def run_batch(
    campaigns: List[tuple],
    out_dir: str,
    qr: bool = False,
    html_index: bool = False,
    qr_backend: Optional[Backend] = None,
    taxonomy: Optional[Taxonomy] = None,
    fix: bool = False,
    ga4: bool = False,
) -> BatchResult:
    """Build every valid row. Rows with an *error* finding are skipped (fail closed)."""
    result = BatchResult()
    os.makedirs(out_dir, exist_ok=True)
    backend = None
    if qr:
        try:
            backend = get_backend(qr_backend)
        except QrUnavailable as e:
            result.findings.append(Finding("warn", "qr_unavailable", "", str(e)))
    if fix:
        fixed = []
        for row_no, c in campaigns:
            c2, changes = fix_campaign(c, taxonomy)
            for ch in changes:
                result.findings.append(Finding("info", "fixed", f"row {row_no}", ch))
            fixed.append((row_no, c2))
        campaigns = fixed
    result.findings.extend(validate_rows(campaigns))
    taken: set = set()
    counters: dict = {}
    for row_no, campaign in campaigns:
        where = f"row {row_no}"
        row_findings = validate_campaign(campaign, where=where, ga4=ga4)
        if taxonomy is not None:
            row_findings.extend(check_taxonomy(campaign, taxonomy, where))
        result.findings.extend(row_findings)
        if any(f.severity == "error" for f in row_findings):
            continue
        url = build_url(campaign)
        base = slugify(campaign.name or (campaign.url + url))
        if base in taken:  # resume numbering instead of rescanning -2, -3 ... (O(1) amortised)
            n = counters.get(base, 2)
            while f"{base}-{n}" in taken:
                n += 1
            counters[base] = n + 1
            slug = f"{base}-{n}"
        else:
            slug = base
        taken.add(slug)
        ch = ga4_channel(campaign.source, campaign.medium, campaign.campaign)
        entry = {"slug": slug, "url": campaign.url, "final_url": url, "qr": "",
                 "name": campaign.name, "ga4_channel": ch.name if campaign.medium else "",
                 **{k: getattr(campaign, a) for k, a in _OUT_UTM}}
        if backend is not None:
            qr_path = os.path.join(out_dir, f"{slug}.png")
            try:
                backend(url, qr_path)
                entry["qr"] = os.path.basename(qr_path)
                result.qr_written.append(qr_path)
            except Exception as e:  # backend failure shouldn't kill the batch
                result.findings.append(Finding("warn", "qr_failed", where, sanitize(str(e))))
        result.rows.append(entry)
    if html_index:
        write_html_index(result, os.path.join(out_dir, "index.html"))
    return result


_OUT_UTM = (("utm_source", "source"), ("utm_medium", "medium"), ("utm_campaign", "campaign"),
            ("utm_term", "term"), ("utm_content", "content"), ("utm_id", "id"),
            ("utm_source_platform", "source_platform"),
            ("utm_creative_format", "creative_format"),
            ("utm_marketing_tactic", "marketing_tactic"))
CSV_FIELDS = ["slug", "final_url", "qr", "name", "ga4_channel"] + [k for k, _ in _OUT_UTM]


def _csv_safe(value: str) -> str:
    """Neutralise spreadsheet formula injection (OWASP CSV injection)."""
    return "'" + value if value[:1] in ("=", "+", "-", "@", "\t", "\r") else value


def write_csv(result: BatchResult, path: str) -> None:
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=CSV_FIELDS, extrasaction="ignore")
        writer.writeheader()
        for row in result.rows:
            writer.writerow({k: _csv_safe(str(row.get(k, ""))) for k in CSV_FIELDS})


def write_html_index(result: BatchResult, path: str) -> None:
    lines = ["<!doctype html><meta charset='utf-8'>",
             "<meta http-equiv='Content-Security-Policy' content=\"default-src 'none'; "
             "img-src 'self'; style-src 'unsafe-inline'\">",
             "<title>Campaign links</title>",
             "<table border='1' cellpadding='6'><tr><th>slug</th><th>link</th>"
             "<th>GA4 channel</th><th>QR</th></tr>"]
    for row in result.rows:
        qr_cell = (f"<img src='{html.escape(row['qr'])}' width='120' alt='QR'>"
                   if row["qr"] else "")
        u = row["final_url"]
        link = html.escape(sanitize(u))
        cell = (f"<a href='{html.escape(u)}' rel='noopener noreferrer'>{link}</a>"
                if u.lower().startswith(("http://", "https://")) else link)
        lines.append(
            f"<tr><td>{html.escape(row['slug'])}</td><td>{cell}</td>"
            f"<td>{html.escape(row.get('ga4_channel', ''))}</td><td>{qr_cell}</td></tr>"
        )
    lines.append("</table>")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))
