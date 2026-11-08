"""utmkit CLI: build single links or batches from a spec CSV."""
from __future__ import annotations

import argparse
import sys

from . import __version__
from .batch import load_campaigns, run_batch, write_csv
from .core import Campaign, build_url, validate_campaign


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):  # Windows cp1252 consoles choke on non-Latin values
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
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
    g.add_argument("--qr", metavar="PNG", help="also write a QR code to this path")

    b = sub.add_parser("batch", help="build many tracked URLs from a CSV spec")
    b.add_argument("spec", help="CSV with columns: url, source, medium, campaign[, term, content, name]")
    b.add_argument("--out-dir", default="utmkit-out")
    b.add_argument("--qr", action="store_true", help="write QR PNGs (needs utmkit[qr])")
    b.add_argument("--html", action="store_true", help="also write index.html linking everything")
    b.add_argument("--strict", action="store_true", help="validation warnings exit non-zero")

    v = sub.add_parser("validate", help="check a spec CSV without building anything")
    v.add_argument("spec")
    v.add_argument("--strict", action="store_true")

    args = ap.parse_args(argv)

    if args.cmd == "gen":
        campaign = Campaign(url=args.url, source=args.source, medium=args.medium,
                            campaign=args.campaign, term=args.term, content=args.content)
        findings = validate_campaign(campaign, where="gen")
        errors = [f for f in findings if f.severity == "error"]
        for f in findings:
            print(f"{f.severity.upper():5} {f.code}: {f.detail}", file=sys.stderr)
        if errors:
            return 1
        url = build_url(campaign)
        print(url)
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
        campaigns = load_campaigns(args.spec)
    except (FileNotFoundError, ValueError) as e:
        print(f"utmkit: {e}", file=sys.stderr)
        return 2

    if args.cmd == "validate":
        findings = [f for row, c in campaigns for f in validate_campaign(c, where=f"row {row}")]
        for f in findings:
            print(f"{f.severity.upper():5} {f.where}: {f.code}: {f.detail}")
        print(f"{len(findings)} finding(s)")
        return 1 if any(f.severity == "error" for f in findings) or (args.strict and findings) else 0

    result = run_batch(campaigns, out_dir=args.out_dir, qr=args.qr, html_index=args.html)
    out_csv = f"{args.out_dir}/links.csv"
    write_csv(result, out_csv)
    errors = [f for f in result.findings if f.severity == "error"]
    warns = [f for f in result.findings if f.severity == "warn"]
    for f in result.findings:
        print(f"{f.severity.upper():5} {f.where}: {f.code}: {f.detail}", file=sys.stderr)
    print(f"{len(result.rows)} link(s) -> {out_csv}"
          + (f", {len(result.qr_written)} QR code(s)" if result.qr_written else ""))
    if errors or (args.strict and warns):
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
