# utmkit

**Campaign links, done consistently.** Batch-build UTM-tagged URLs from a CSV spec without touching the rest of your URL, check them (and links you already published) against GA4's own channel rules and your naming convention, catch spellings that drifted from earlier batches, verify that redirects keep the tags, and get QR codes plus a static index page. Offline except `check`, free, zero dependencies.

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

- **error** (row is skipped, exit 1): no url / non-http(s) scheme such as `javascript:` / no host or a bad port (`https://ex.com:abc/`) / spaces or control or invisible characters in values / missing `utm_source`
- **warn**: an email address in a value (analytics terms forbid personal data in URLs), uppercase (GA4 values are case sensitive), spaces, already percent-encoded values, missing `utm_medium` / `utm_campaign` (GA4 shows `(not set)`), a medium that lands in GA4's **Unassigned** channel (e.g. `qr`, `print`), a utm already in the URL being replaced, URLs over 2000 chars
- **across rows**: `Instagram` vs `instagram`, `paid-social` vs `paid_social`, and two rows that build the identical link
- `--strict` makes warnings fail the run; `--no-ga4` turns the GA4-specific checks off; informational `fixed` notes never fail it.

### Links you already published (`audit`)

```bash
utmkit audit live-links.txt          # one URL per line, or a CSV with a url column
utmkit taxonomy-init live-links.txt --out rules.json   # starter naming rules from what you already use
```

`audit` reads the `utm_*` values back out of each URL and runs the same checks as `validate` (an untagged URL is an error). `taxonomy-init` writes a starter [taxonomy](#naming-convention---taxonomy---fix): the spellings you use become the allowed list, and spellings that differ only by case or punctuation (`Instagram`, `insta-gram`) become aliases of the most common one. Review the file before enforcing it.

### Drift across batches (`--history`)

```bash
utmkit batch q2.csv --history q1-out/links.csv
# WARN row 3: history_variant: source='Instagram' was 'instagram' in earlier links; GA4 will report them separately
```

Flags values that match an earlier batch's value except for case or punctuation, and links that are identical to one you already made. Works with `validate` and `audit` too.

### One row, many links (`--expand`)

With `batch --expand` (or `validate --expand`), `a|b` in a `source`/`medium`/`campaign`/`term`/`content`/... cell makes one link per value, all combinations: `source=instagram|facebook` and `content=a|b` give four links, and the `name` gets the values appended. Off by default, so a literal `|` in your values is untouched. More than 200,000 links stops the run.

### Machine-readable output

`validate`, `audit` and `batch` take `--format json` and print one JSON document (`findings`, plus row/link counts) on stdout; `check --format json` prints per-row results. Control and bidi characters are escaped. Exit codes: 0 clean, 1 errors (or warnings with `--strict`), 2 unreadable input/taxonomy/output folder.

### Naming convention (`--taxonomy`, `--fix`)

```json
{"fields": {"source": {"allowed": ["instagram", "newsletter"], "aliases": {"ig": "instagram"}},
            "medium": {"allowed": ["social", "email", "cpc"]},
            "campaign": {"pattern": "[a-z0-9]+-[0-9]{2}", "max_length": 40}},
 "required": ["source", "medium", "campaign"]}
```

`utmkit batch spec.csv --taxonomy rules.json --fix` lowercases, turns spaces into dashes and applies aliases, reports each change, then enforces the rules (`gen` takes `--taxonomy` and `--fix` as well). A malformed taxonomy file stops the run (exit 2) instead of checking nothing.

`pattern` regexes are screened when the file loads: patterns that can hang the checker (nested repeats such as `(a+)+`, overlapping alternations such as `(a|ab)*`, three or more overlapping `.*`) are rejected with an error, patterns over 300 characters are rejected, and values over 200 characters are reported as non-matching without running the regex. The screen is a heuristic, not a proof: it does not analyse conditionals or atomic groups, so keep patterns simple.

### GA4 channel preview

`gen` and `links.csv` show which **default channel group** the link will land in (Paid Search, Email, Organic Social, Unassigned, ...). Rules follow [Google's channel definitions](https://support.google.com/analytics/answer/9756891); Google compares sources against long lists that utmkit only partly copies, so unsure answers are marked `uncertain`. Also supported: `utm_id`, `utm_source_platform`, `utm_creative_format`, `utm_marketing_tactic` ([Google's list](https://support.google.com/analytics/answer/10917952); Google says the last two are not yet reported in GA properties).

### Do the tags survive redirects?

```bash
utmkit check spec.csv        # follows each link's redirects (HEAD, no body)
# OK    row 2: 200 after 1 redirect(s)
# FAIL  row 3: redirect chain dropped utm_medium, utm_source
```

The report names the hop where the tags were first lost, and also fails a chain that kept a tag but changed its value. Only globally routable http(s) hosts are contacted unless `--allow-private` (loopback, private, link-local, carrier-grade NAT `100.64/10`, reserved, and IPv4 addresses hidden in IPv4-mapped, 6to4 or NAT64 IPv6 forms are refused). Each host is resolved once and the connection goes to that checked address, so there is no re-lookup window for DNS rebinding; TLS still verifies the certificate against the host name. At most 2 requests run at once against the same host. JavaScript / meta-refresh redirects are not followed.

## Design notes

- **Deterministic slugs**: the `name` column (else the URL) becomes the filename slug; collisions get `-2`, `-3` suffixes — same input, same output names, every run.
- **Existing params survive byte-for-byte**: the original query string (flags, `;`, `+`, signed tokens) is not re-encoded; only the nine managed `utm_*` keys are replaced by the campaign (the campaign is the source of truth); custom `utm_*` keys are kept.
- **Spec files from Excel**: BOM, `;` delimiter, headers like `utm_source` or `Landing Page`; unknown/misspelt columns are reported (`campain` -> did you mean `campaign`?).
- **Safe outputs**: control/bidi characters are escaped in messages, `links.csv` cells starting with `=+-@` are prefixed with `'` (spreadsheet formula injection), `index.html` only links http(s) and carries a locked-down CSP. Slugs are capped at 80 chars, avoid Windows device names (`con`, `nul`...) and non-Latin names get `link-<hash>`.
- **QR is optional**: the core has zero dependencies; `qrcode` is only imported when you pass `--qr` and installs via the `[qr]` extra. Custom backends can be injected through the Python API.
- **Static `index.html`**: host it, print it, or hand it to whoever is running the campaign — no JS, no build step.

## How it compares

Measured with `python bench/bench.py` (stdlib only, seeded, re-runnable; the older algorithms are embedded for before/after; throughput is best of 3 on a shared machine, so treat it as rough):

| | utmkit now | utmkit 0.1 / 0.2 | `utm-builder` 0.0.1 (npm, library) |
|---|---|---|---|
| Non-UTM query kept byte-for-byte (5000 URLs with flags, `;`, `+`, `%2F`) | 100% | 33.2% (0.1) | 33.1% |
| 1500 identical names, slug allocation | 0.05-0.07 s whole batch | 6-7 s (0.1, slug step alone) | n/a |
| Seeded defects caught by exact code (12: scheme, GA4 Unassigned, missing campaign/medium, case/near-dup/dup link, invisible chars, bad port, email in a value, ...) | 12/12 | 0/12 (0.1) | not measured (library only validates empties) |
| Non-public redirect targets refused (13 address forms) | 13/13 | 11/13 (0.2: missed `100.64.0.1`, `100.127.255.254`) | n/a |
| Taxonomy regex `(a+)+$` | rejected at load (< 1 ms) | ran it: 0.2-0.25 s on a 23-char value, doubling per added character (0.2) | n/a |
| Batch build+validate+slug, 20k rows | 17-22k rows/s | about 10k rows/s (0.2) | n/a |

| Tool | Bulk from CSV | Audit existing links | Cross-row / cross-batch consistency | Naming rules | GA4 channel preview | Redirect check | Offline / free |
|---|---|---|---|---|---|---|---|
| utmkit | yes | yes | yes / yes (`--history`) | yes (JSON) | yes | yes | yes |
| [Google Campaign URL Builder](https://ga-dev-tools.google/ga4/campaign-url-builder/) | unverified (single-link web form as far as we know; the page is client-rendered and our fetcher could not read it) | unverified | no | no | no | no | free, online |
| UTM.io, Terminus ([blog](https://www.terminusapp.com/blog/utm-source-platform/)) | unverified (commercial, not tested; pricing not checked) | unverified | unverified | unverified | unverified | unverified | no |
| Spreadsheet templates | manual formulas | manual | unverified | unverified | no | no | yes |
| `utm-cli` 1.0.0 (npm) | no | no | no | no | no | no | crashes on start with Node 22 (ESM import error, tested 2026-11) |

"unverified" means we did not test it; check vendors' current pages before relying on this table. A PyPI search for 14 plausible package names (utm-builder, utm-tagger, utmify, ...) found no other UTM-link tool (`pyutm` is a map-coordinate library, unrelated), but PyPI has no real search API here, so a miss is possible.

## Limits

- GA4 channel prediction uses a partial source list (see above); QR codes need `utmkit[qr]`.
- `check` follows HTTP redirects only and needs network access. The pinned HTTPS path was verified by hand against a local self-signed server, not in the automated tests (they need no OpenSSL and no network).
- `--history` and `taxonomy-init` compare spellings only (case and punctuation); they do not know that `ig` means `instagram` unless your taxonomy says so.
- Email detection is a simple pattern; it will miss obfuscated addresses and flags `user@host` lookalikes.
- Tested on Python 3.13 (full suite) and 3.11 / 3.12 (import and regex-screen smoke test only); 3.9 is declared in `pyproject.toml` but was not run here.
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
