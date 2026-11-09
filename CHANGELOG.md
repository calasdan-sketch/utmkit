# Changelog

## 0.1.0 - 2026-11-08

First release on PyPI.

- `utmkit` CLI that builds batches of UTM-tagged campaign links from CSV with consistent slugs and validation.
- Optional `--rules` allow-list for source, medium and campaign; warns on duplicate final URLs.
- `parse` command to decode and check a tagged URL.
- Optional QR codes (SVG needs only the `qrcode` package; PNG needs the `qr` extra) and a static index page.
