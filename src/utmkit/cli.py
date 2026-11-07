"""utmkit CLI: build single links or batches from a spec CSV."""
from __future__ import annotations

import argparse
import sys

from . import __version__
from .batch import load_spec, run_batch, write_csv
from .channels import ga4_channel
from .check import check_url
from .core import Campaign, build_url, sanitize, validate_campaign, validate_rows
from .taxonomy import check_taxonomy, load_taxonomy


def main(argv: list[str] | None = None) -> int:
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

    v = sub.add_parser("validate", help="check a spec CSV without building anything")
    v.add_argument("spec")
    v.add_argument("--taxonomy", metavar="JSON", help="enforce a naming-convention file")
    v.add_argument("--no-ga4", action="store_true", help="skip GA4-specific checks")
    v.add_argument("--strict", action="store_true")

    k = sub.add_parser("check", help="follow each link's redirects; report if UTM params survive")
    k.add_argument("spec")
    k.add_argument("--allow-private", action="store_true",
                   help="also allow localhost / private-network targets")
    k.add_argument("--timeout", type=float, default=10.0)
    k.add_argument("--workers", type=int, default=8)

    args = ap.parse_args(argv)

    if args.cmd == "gen":
        campaign = Campaign(url=args.url, source=args.source, medium=args.medium,
                            campaign=args.campaign, term=args.term, content=args.content,
                            id=args.id, source_platform=args.source_platform)
        findings = validate_campaign(campaign, where="gen", ga4=not args.no_ga4)
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

    try:
        campaigns, file_findings = load_spec(args.spec)
        tax = load_taxonomy(args.taxonomy) if getattr(args, "taxonomy", None) else None
    except (OSError, ValueError) as e:
        print(f"utmkit: {sanitize(str(e))}", file=sys.stderr)
        return 2

    def show(f, out=sys.stdout):
        print(f"{f.severity.upper():5} {f.where}: {f.code}: {f.detail}", file=out)

    if args.cmd == "check":
        from concurrent.futures import ThreadPoolExecutor
        from .core import build_url as _bu
        urls = []
        for row, c in campaigns:
            try:
                urls.append((row, _bu(c)))
            except ValueError:
                print(f"SKIP  row {row}: no url")
        with ThreadPoolExecutor(max_workers=max(1, min(args.workers, 32))) as ex:
            results = list(ex.map(lambda t: check_url(t[1], args.allow_private, timeout=args.timeout), urls))
        bad = 0
        for (row, _), r in zip(urls, results):
            if r.ok:
                print(f"OK    row {row}: {r.status} after {len(r.hops) - 1} redirect(s)")
            else:
                bad += 1
                print(f"FAIL  row {row}: {r.problem}")
        print(f"{len(results) - bad}/{len(results)} link(s) keep their UTM parameters")
        return 1 if bad else 0

    ga4 = not args.no_ga4
    if args.cmd == "validate":
        findings = list(file_findings) + validate_rows(campaigns)
        for row, c in campaigns:
            findings.extend(validate_campaign(c, where=f"row {row}", ga4=ga4))
            if tax:
                findings.extend(check_taxonomy(c, tax, f"row {row}"))
        for f in findings:
            show(f)
        print(f"{len(findings)} finding(s)")
        return 1 if any(f.severity == "error" for f in findings) or (
            args.strict and any(f.severity != "info" for f in findings)) else 0

    result = run_batch(campaigns, out_dir=args.out_dir, qr=args.qr, html_index=args.html,
                       taxonomy=tax, fix=args.fix, ga4=ga4)
    result.findings = list(file_findings) + result.findings
    out_csv = f"{args.out_dir}/links.csv"
    write_csv(result, out_csv)
    errors = [f for f in result.findings if f.severity == "error"]
    warns = [f for f in result.findings if f.severity == "warn"]
    for f in result.findings:
        show(f, sys.stderr)
    skipped = len(campaigns) - len(result.rows)
    print(f"{len(result.rows)} link(s) -> {out_csv}"
          + (f", {len(result.qr_written)} QR code(s)" if result.qr_written else "")
          + (f", {skipped} row(s) skipped because of errors" if skipped else ""))
    if errors or (args.strict and warns):
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
