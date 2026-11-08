# utmkit

**Campaign links, done consistently.** Batch-build UTM-tagged URLs from a CSV spec, with deterministic file slugs, validation that catches the mistakes that silently wreck analytics, optional QR codes, and a static index page you can host or print.

## Install

```bash
pip install utmkit            # links, slugs, validation
pip install 'utmkit[qr]'      # + QR code generation
```

## One link

```bash
utmkit gen https://calasautomations.com/onfile \
  --source instagram --medium social --campaign launch26
# https://calasautomations.com/onfile?utm_source=instagram&utm_medium=social&utm_campaign=launch26

utmkit gen ... --qr launch26-ig.png    # QR for the same URL (needs [qr] extra)
```

## Batch

`spec.csv`:

```csv
url,source,medium,campaign,name
https://calasautomations.com/onfile,instagram,social,launch26,Spring Ad
https://calasautomations.com/quote,newsletter,email,launch26,Quote Nudge
```

```bash
utmkit batch spec.csv --out-dir out/ --qr --html
```

Produces `out/links.csv` (slug, final URL, QR filename), one QR PNG per row when enabled, and `out/index.html` — a table of every link with clickable URLs and QR images.

## Validation

`utmkit validate spec.csv` flags the classics without building anything:

- **error** — missing `utm_source`, empty URL
- **warn** — uppercase values (analytics tools split `Instagram` from `instagram`), spaces in values, unusual `utm_medium` values, URLs without a scheme

Warnings don't fail the build unless `--strict`. In `batch`, a row with an error is reported and skipped (no link built) and the run exits 1.

## Design notes

- **Deterministic slugs**: the `name` column (else the final tagged URL) becomes the filename slug; collisions get `-2`, `-3` suffixes — same input, same output names, every run.
- **Existing params survive**: `?id=7&ref=nav` stays intact; stale values for the five standard keys (`utm_source`, `utm_medium`, `utm_campaign`, `utm_term`, `utm_content`) are replaced by the campaign (the campaign is the source of truth); other params such as `utm_id` are kept.
- **QR is optional**: the core has zero dependencies; `qrcode` is only imported when you pass `--qr` and installs via the `[qr]` extra. Custom backends can be injected through the Python API.
- **Static `index.html`**: host it, print it, or hand it to whoever is running the campaign — no JS, no build step.

## Python API

```python
from utmkit import Campaign, build_url, slugify

url = build_url(Campaign("https://ex.com", source="ig", medium="social", campaign="c1"))
assert slugify("Spring Sale — 20% OFF!") == "spring-sale-20-off"
```

## License

MIT-style: use it, ship it, no warranty.
