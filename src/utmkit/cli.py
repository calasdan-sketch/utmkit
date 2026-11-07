"""utmkit CLI: build single links or batches from a spec CSV."""
from __future__ import annotations

import argparse
import json
import os
import sys

from . import __version__
from .batch import expand_campaigns, load_spec, load_urls, run_batch, write_csv
from .history import check_history, load_history
from .channels import ga4_channel
from .core import Campaign, Finding, build_url, has_unsafe, sanitize, validate_campaign, validate_rows
from .taxonomy import check_taxonomy, fix_campaign, load_taxonomy, suggest_taxonomy


def main(argv: list[str] | None = None) -> int:
    try:
        return _main(argv)
    except BrokenPipeError:  # `utmkit ... | head`
        try:
            sys.stdout = open(os.devnull, "w")
        except OSError:
            pass
        return 0


def _main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="utmkit", description="Batch UTM campaign links + QR codes.")
    ap.add_argument("--version", action="version", version=f"utmkit {__version__}")
    sub = ap.add_subparsers(dest="cmd", required=True)

    g = sub.add_parser("gen", help="build one tracked URL")
    g.add_argument("url")
    g.add_argument("--source", default="")
    g.add_argument("--medium", default="")
    g.add_argument("--campaign", default="")
    g.add_argument("--term", default="")
    g.add_argument("--content", default="")
    g.add_argument("--id", default="", help="utm_id (GA4 campaign id)")
    g.add_argument("--source-platform", default="", help="utm_source_platform")
    g.add_argument("--no-ga4", action="store_true", help="skip GA4-specific checks")
    g.add_argument("--taxonomy", metavar="JSON", help="enforce a naming-convention file")
    g.add_argument("--fix", action="store_true", help="normalise values (lowercase, dashes, aliases)")
    g.add_argument("--qr", metavar="PNG", help="also write a QR code to this path")

    b = sub.add_parser("batch", help="build many tracked URLs from a CSV spec")
    b.add_argument("spec", help="CSV with columns: url, source, medium, campaign[, term, content, name]")
    b.add_argument("--out-dir", default="utmkit-out")
    b.add_argument("--qr", action="store_true", help="write QR PNGs (needs utmkit[qr])")
    b.add_argument("--html", action="store_true", help="also write index.html linking everything")
    b.add_argument("--taxonomy", metavar="JSON", help="enforce a naming-convention file")
    b.add_argument("--fix", action="store_true", help="normalise values (lowercase, dashes, aliases)")
    b.add_argument("--no-ga4", action="store_true", help="skip GA4-specific checks")
    b.add_argument("--strict", action="store_true", help="validation warnings exit non-zero")
    b.add_argument("--history", metavar="CSV", help="earlier links.csv: flag values spelled differently before")
    b.add_argument("--expand", action="store_true", help="a|b in a utm cell makes one link per value (all combinations)")
    b.add_argument("--format", choices=("text", "json"), default="text", help="json: one machine-readable document on stdout")

    v = sub.add_parser("validate", help="check a spec CSV without building anything")
    v.add_argument("spec")
    v.add_argument("--taxonomy", metavar="JSON", help="enforce a naming-convention file")
    v.add_argument("--no-ga4", action="store_true", help="skip GA4-specific checks")
    v.add_argument("--strict", action="store_true")
    v.add_argument("--history", metavar="CSV", help="earlier links.csv: flag values spelled differently before")
    v.add_argument("--expand", action="store_true", help="a|b in a utm cell makes one link per value (all combinations)")
    v.add_argument("--format", choices=("text", "json"), default="text")

    a = sub.add_parser("audit", help="check links that are already tagged (URL list or CSV with a url column)")
    a.add_argument("file", help="text file with one URL per line, or a CSV with a url column")
    a.add_argument("--taxonomy", metavar="JSON")
    a.add_argument("--no-ga4", action="store_true")
    a.add_argument("--strict", action="store_true")
    a.add_argument("--history", metavar="CSV")
    a.add_argument("--format", choices=("text", "json"), default="text")

    t = sub.add_parser("taxonomy-init", help="write starter naming rules from the spellings in existing links")
    t.add_argument("file", help="spec CSV, URL list, or CSV with a url column")
    t.add_argument("--out", metavar="JSON", help="write here instead of stdout")

    k = sub.add_parser("check", help="follow each link's redirects; report if UTM params survive")
    k.add_argument("spec")
    k.add_argument("--allow-private", action="store_true",
                   help="also allow localhost / private-network targets")
    k.add_argument("--timeout", type=float, default=10.0)
    k.add_argument("--workers", type=int, default=8)
    k.add_argument("--format", choices=("text", "json"), default="text")

    args = ap.parse_args(argv)

    if args.cmd == "gen":
        campaign = Campaign(url=args.url, source=args.source, medium=args.medium,
                            campaign=args.campaign, term=args.term, content=args.content,
                            id=args.id, source_platform=args.source_platform)
        tax = None
        if args.taxonomy:
            try:
                tax = load_taxonomy(args.taxonomy)
            except (OSError, ValueError) as e:
                print(f"utmkit: {sanitize(str(e))}", file=sys.stderr)
                return 2
        if args.fix:
            campaign, changes = fix_campaign(campaign, tax)
            for ch in changes:
                print(f"INFO  fixed: {ch}", file=sys.stderr)
        findings = validate_campaign(campaign, where="gen", ga4=not args.no_ga4)
        if tax:
            findings.extend(check_taxonomy(campaign, tax, "gen"))
        errors = [f for f in findings if f.severity == "error"]
        for f in findings:
            print(f"{f.severity.upper():5} {f.code}: {f.detail}", file=sys.stderr)
        if errors:
            return 1
        url = build_url(campaign)
        print(url)
        if campaign.medium and not args.no_ga4:
            ch = ga4_channel(campaign.source, campaign.medium, campaign.campaign)
            print(f"GA4 default channel: {ch.name}" + ("" if ch.certain else " (uncertain)"),
                  file=sys.stderr)
        if args.qr:
            from .qr import QrUnavailable, get_backend
            try:
                get_backend()(url, args.qr)
                print(f"QR written: {args.qr}", file=sys.stderr)
            except QrUnavailable as e:
                print(f"{e}", file=sys.stderr)
                return 1
        return 0

    path = getattr(args, "spec", None) or args.file
    try:
        if args.cmd in ("audit", "taxonomy-init"):
            campaigns, file_findings = load_urls(path)
        else:
            campaigns, file_findings = load_spec(path)
        if getattr(args, "expand", False):
            campaigns = expand_campaigns(campaigns)
        tax = load_taxonomy(args.taxonomy) if getattr(args, "taxonomy", None) else None
        hist = load_history(args.history) if getattr(args, "history", None) else None
    except (OSError, ValueError) as e:
        print(f"utmkit: {sanitize(str(e))}", file=sys.stderr)
        return 2

    as_json = getattr(args, "format", "text") == "json"

    def show(f, out=sys.stdout):
        print(f"{f.severity.upper():5} {f.where}: {f.code}: {f.detail}", file=out)

    def emit(findings, **extra):
        # ensure_ascii escapes control and bidi characters, so the document is safe to print
        doc = {"findings": [{"severity": f.severity, "code": f.code, "where": f.where,
                             "detail": f.detail} for f in findings], **extra}
        print(json.dumps(doc, indent=2, ensure_ascii=True))

    if args.cmd == "taxonomy-init":
        text = json.dumps(suggest_taxonomy(campaigns), indent=2, ensure_ascii=True, sort_keys=False)
        if args.out:
            try:
                with open(args.out, "w", encoding="utf-8") as fh:
                    fh.write(text + "\n")
            except OSError as e:
                print(f"utmkit: {sanitize(str(e))}", file=sys.stderr)
                return 2
            print(f"wrote {args.out}; review it before using --taxonomy", file=sys.stderr)
        else:
            print(text)
        return 0

    if args.cmd == "check":
        from .check import check_many
        from .core import build_url as _bu
        urls = []
        for row, c in campaigns:
            try:
                urls.append((row, _bu(c)))
            except ValueError:
                print(f"SKIP  row {row}: no url")
        results = check_many([u for _, u in urls], args.allow_private, timeout=args.timeout,
                             workers=args.workers)
        bad = 0
        if as_json:
            items = []
            for (row, _), r in zip(urls, results):
                bad += 0 if r.ok else 1
                items.append({"row": row, "ok": r.ok, "status": r.status, "redirects": max(0, len(r.hops) - 1),
                              "lost": r.lost, "changed": r.changed, "problem": r.problem})
            print(json.dumps({"results": items, "ok": len(results) - bad, "total": len(results)},
                             indent=2, ensure_ascii=True))
            return 1 if bad else 0
        for (row, _), r in zip(urls, results):
            if r.ok:
                print(f"OK    row {row}: {r.status} after {len(r.hops) - 1} redirect(s)")
            else:
                bad += 1
                print(f"FAIL  row {row}: {r.problem}")
        print(f"{len(results) - bad}/{len(results)} link(s) keep their UTM parameters")
        return 1 if bad else 0

    ga4 = not args.no_ga4
    if args.cmd in ("validate", "audit"):
        findings = list(file_findings) + validate_rows(campaigns)
        if hist:
            findings.extend(check_history(campaigns, hist))
        for row, c in campaigns:
            if args.cmd == "audit" and c.url and not c.utm() and not has_unsafe(c.url):
                findings.append(Finding("error", "untagged", f"row {row}",
                                        "url has no utm_* parameters"))
                continue
            findings.extend(validate_campaign(c, where=f"row {row}", ga4=ga4))
            if tax:
                findings.extend(check_taxonomy(c, tax, f"row {row}"))
        if as_json:
            emit(findings, rows=len(campaigns))
        else:
            for f in findings:
                show(f)
            print(f"{len(findings)} finding(s)")
        return 1 if any(f.severity == "error" for f in findings) or (
            args.strict and any(f.severity != "info" for f in findings)) else 0

    out_csv = os.path.join(args.out_dir, "links.csv")
    try:
        result = run_batch(campaigns, out_dir=args.out_dir, qr=args.qr, html_index=args.html,
                           taxonomy=tax, fix=args.fix, ga4=ga4)
        result.findings = list(file_findings) + result.findings
        if hist:
            result.findings.extend(check_history(campaigns, hist))
        write_csv(result, out_csv)
    except OSError as e:
        print(f"utmkit: cannot write output: {sanitize(str(e))}", file=sys.stderr)
        return 2
    errors = [f for f in result.findings if f.severity == "error"]
    warns = [f for f in result.findings if f.severity == "warn"]
    skipped = len(campaigns) - len(result.rows)
    if as_json:
        emit(result.findings, links=len(result.rows), skipped=skipped, csv=out_csv,
             qr=len(result.qr_written))
        return 1 if errors or (args.strict and warns) else 0
    for f in result.findings:
        show(f, sys.stderr)
    print(f"{len(result.rows)} link(s) -> {out_csv}"
          + (f", {len(result.qr_written)} QR code(s)" if result.qr_written else "")
          + (f", {skipped} row(s) skipped because of errors" if skipped else ""))
    if errors or (args.strict and warns):
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
