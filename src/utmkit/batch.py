"""Batch processing: campaign spec CSV -> tracked links, slugs, optional QR + HTML."""
from __future__ import annotations

import csv
import html
import os
from dataclasses import dataclass, field
from typing import List, Optional

from .core import Campaign, Finding, build_url, slugify, unique_slug, validate_campaign
from .qr import Backend, QrUnavailable, get_backend

COLUMNS = ("url", "source", "medium", "campaign", "term", "content", "name")


def load_campaigns(path: str) -> List[tuple]:
    """Read the spec CSV; returns [(row_number, Campaign, original_row)]."""
    out = []
    with open(path, newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        if not reader.fieldnames or "url" not in {f.strip().lower() for f in reader.fieldnames}:
            raise ValueError("spec CSV needs a 'url' column")
        for i, row in enumerate(reader, start=2):
            norm = {(k or "").strip().lower(): (v or "").strip() for k, v in row.items()}
            out.append((i, Campaign(
                url=norm.get("url", ""),
                source=norm.get("source", ""),
                medium=norm.get("medium", ""),
                campaign=norm.get("campaign", ""),
                term=norm.get("term", ""),
                content=norm.get("content", ""),
                name=norm.get("name", ""),
            )))
    return out


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
) -> BatchResult:
    result = BatchResult()
    os.makedirs(out_dir, exist_ok=True)
    backend = None
    if qr:
        try:
            backend = get_backend(qr_backend)
        except QrUnavailable as e:
            result.findings.append(Finding("warn", "qr_unavailable", "", str(e)))
    taken: List[str] = []
    for row_no, campaign in campaigns:
        where = f"row {row_no}"
        result.findings.extend(validate_campaign(campaign, where=where))
        url = build_url(campaign)
        base = slugify(campaign.name or (campaign.url + url))
        slug = unique_slug(base, taken)
        taken.append(slug)
        entry = {"slug": slug, "url": campaign.url, "final_url": url, "qr": ""}
        if backend is not None:
            qr_path = os.path.join(out_dir, f"{slug}.png")
            try:
                backend(url, qr_path)
                entry["qr"] = os.path.basename(qr_path)
                result.qr_written.append(qr_path)
            except Exception as e:  # backend failure shouldn't kill the batch
                result.findings.append(Finding("warn", "qr_failed", where, str(e)))
        result.rows.append(entry)
    if html_index:
        write_html_index(result, os.path.join(out_dir, "index.html"))
    return result


def write_csv(result: BatchResult, path: str) -> None:
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=["slug", "final_url", "qr"])
        writer.writeheader()
        for row in result.rows:
            writer.writerow({k: row[k] for k in ("slug", "final_url", "qr")})


def write_html_index(result: BatchResult, path: str) -> None:
    lines = ["<!doctype html><meta charset='utf-8'><title>Campaign links</title>",
             "<table border='1' cellpadding='6'><tr><th>slug</th><th>link</th><th>QR</th></tr>"]
    for row in result.rows:
        qr_cell = (f"<img src='{html.escape(row['qr'])}' width='120' alt='QR'>"
                   if row["qr"] else "")
        lines.append(
            f"<tr><td>{html.escape(row['slug'])}</td>"
            f"<td><a href='{html.escape(row['final_url'])}'>{html.escape(row['final_url'])}</a></td>"
            f"<td>{qr_cell}</td></tr>"
        )
    lines.append("</table>")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))
