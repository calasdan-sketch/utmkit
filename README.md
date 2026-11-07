# utmkit

**Campaign links, done consistently.** Batch-build UTM-tagged URLs from a CSV spec without touching the rest of your URL, check them against GA4's own channel rules and your naming convention, verify that redirects keep the tags, and get QR codes plus a static index page. Offline, free, zero dependencies.

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

`utmkit validate spec.csv` (and `batch`) flag the mistakes that silently wreck analytics, per row and across rows:

- **error** (row is skipped, exit 1): no url / non-http(s) scheme such as `javascript:` / spaces or control or invisible characters in values / missing `utm_source`
- **warn**: uppercase (GA4 values are case sensitive), spaces, already percent-encoded values, missing `utm_medium` / `utm_campaign` (GA4 shows `(not set)`), a medium that lands in GA4's **Unassigned** channel (e.g. `qr`, `print`), a utm already in the URL being replaced, URLs over 2000 chars
- **across rows**: `Instagram` vs `instagram`, `paid-social` vs `paid_social`, and two rows that build the identical link
- `--strict` makes warnings fail the run; `--no-ga4` turns the GA4-specific checks off; informational `fixed` notes never fail it.

### Naming convention (`--taxonomy`, `--fix`)

```json
{"fields": {"source": {"allowed": ["instagram", "newsletter"], "aliases": {"ig": "instagram"}},
            "medium": {"allowed": ["social", "email", "cpc"]},
            "campaign": {"pattern": "[a-z0-9]+-[0-9]{2}", "max_length": 40}},
 "required": ["source", "medium", "campaign"]}
```

`utmkit batch spec.csv --taxonomy rules.json --fix` lowercases, turns spaces into dashes and applies aliases, reports each change, then enforces the rules. A malformed taxonomy file stops the run (exit 2) instead of checking nothing.

### GA4 channel preview

`gen` and `links.csv` show which **default channel group** the link will land in (Paid Search, Email, Organic Social, Unassigned, ...). Rules follow [Google's channel definitions](https://support.google.com/analytics/answer/9756891); Google compares sources against long lists that utmkit only partly copies, so unsure answers are marked `uncertain`. Also supported: `utm_id`, `utm_source_platform`, `utm_creative_format`, `utm_marketing_tactic` ([Google's list](https://support.google.com/analytics/answer/10917952); Google says the last two are not yet reported in GA properties).

### Do the tags survive redirects?

```bash
utmkit check spec.csv        # follows each link's redirects (HEAD, no body)
# OK    row 2: 200 after 1 redirect(s)
# FAIL  row 3: redirect chain dropped utm_medium, utm_source
```

Only public http(s) hosts unless `--allow-private`. JavaScript / meta-refresh redirects are not followed. There is a DNS-rebinding window between the address check and the connection, so do not run `check` on untrusted spec files from a machine with sensitive internal services.

## Design notes

- **Deterministic slugs**: the `name` column (else the URL) becomes the filename slug; collisions get `-2`, `-3` suffixes — same input, same output names, every run.
- **Existing params survive byte-for-byte**: the original query string (flags, `;`, `+`, signed tokens) is not re-encoded; only the nine managed `utm_*` keys are replaced by the campaign (the campaign is the source of truth); custom `utm_*` keys are kept.
- **Spec files from Excel**: BOM, `;` delimiter, headers like `utm_source` or `Landing Page`; unknown/misspelt columns are reported (`campain` -> did you mean `campaign`?).
- **Safe outputs**: control/bidi characters are escaped in messages, `links.csv` cells starting with `=+-@` are prefixed with `'` (spreadsheet formula injection), `index.html` only links http(s) and carries a locked-down CSP. Slugs are capped at 80 chars, avoid Windows device names (`con`, `nul`...) and non-Latin names get `link-<hash>`.
- **QR is optional**: the core has zero dependencies; `qrcode` is only imported when you pass `--qr` and installs via the `[qr]` extra. Custom backends can be injected through the Python API.
- **Static `index.html`**: host it, print it, or hand it to whoever is running the campaign — no JS, no build step.

## How it compares

Measured with `python bench/bench.py` (stdlib only, seeded, re-runnable; v0.1.0 algorithms are embedded for before/after):

| | utmkit 0.2 | utmkit 0.1 | `utm-builder` 0.0.1 (npm, library) |
|---|---|---|---|
| Non-UTM query kept byte-for-byte (5000 URLs with flags, `;`, `+`, `%2F`) | 100% | 33.2% | 33.1% |
| 1500 identical names, slug allocation | 0.04 s whole batch | 4.0 s (slug step alone) | n/a |
| Seeded defects caught by exact code (10: scheme, GA4 Unassigned, missing campaign/medium, case/near-dup/dup link, invisible chars, ...) | 10/10 | 0/10 (a `javascript:` URL got a `no_scheme` warning but was still built) | not measured (library only validates empties) |

| Tool | Bulk from CSV | Cross-row consistency | Naming rules | GA4 channel preview | Redirect check | Offline / free |
|---|---|---|---|---|---|---|
| utmkit 0.2 | yes | yes | yes (JSON) | yes | yes | yes |
| [Google Campaign URL Builder](https://ga-dev-tools.google/ga4/campaign-url-builder/) | unverified (single-link web form as far as we know; page would not render for our fetcher) | no | no | no | no | free, online |
| UTM.io, Terminus ([blog](https://www.terminusapp.com/blog/utm-source-platform/)) | unverified (commercial, not tested; pricing not checked) | unverified | unverified | unverified | unverified | no |
| Spreadsheet templates | manual formulas | unverified | unverified | no | no | yes |
| `utm-cli` 1.0.0 (npm) | no | no | no | no | no | crashes on start with Node 22 (ESM import error, tested) |

"unverified" means we did not test it; check vendors' current pages before relying on this table.

## Limits

- GA4 channel prediction uses a partial source list (see above); QR codes need `utmkit[qr]`.
- `check` follows HTTP redirects only and needs network access.
- The 2000-character URL warning is a conservative rule of thumb, not a documented per-platform limit.
- `links.csv` gained columns after the original three (`slug,final_url,qr`); rows with errors are no longer written to it.

## Python API

```python
from utmkit import Campaign, build_url, slugify

url = build_url(Campaign("https://ex.com", source="ig", medium="social", campaign="c1"))
assert slugify("Spring Sale — 20% OFF!") == "spring-sale-20-off"
```

## License

MIT-style: use it, ship it, no warranty.
