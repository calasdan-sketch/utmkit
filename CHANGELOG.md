# Changelog

## 0.2.0 (unreleased)

Added (round 3)
- `utmkit audit FILE`: validate links that are already tagged (URL-per-line file or CSV with a `url` column); `utmkit taxonomy-init FILE [--out JSON]` writes starter naming rules from existing spellings.
- `--history links.csv` (batch/validate/audit): `history_variant` and `history_duplicate` findings against earlier batches.
- `--expand` (batch/validate): `a|b` cells make one link per combination (refuses > 200,000 links).
- `--format json` for validate, audit, batch, check (control/bidi characters escaped); `gen` accepts `--taxonomy` and `--fix`.
- New findings `bad_host` (error: no host / bad port / malformed brackets) and `pii_email` (warn). Tab-delimited specs are detected.
- `check`: names the hop where tags were first lost, fails chains that rewrite a value (`changed`), limits to 2 concurrent requests per host, and one failing worker can no longer abort the run (`check_many`).
- `bench/bench.py`: hostile-input section (address forms refused, catastrophic regex), best-of-3 throughput, two new seeded defects.

Fixed (round 3)
- Security: taxonomy `pattern` regexes were only length-guarded, so `(a+)+$` or `.*.*.*.*x` could hang `validate`/`batch` on a 25-character value. Patterns are now screened at load (nested/overlapping repeats rejected, 300-char limit, values capped at 200 chars). This is a behaviour change: such patterns now stop the run with exit 2.
- Security: `check` accepted carrier-grade NAT (`100.64.0.0/10`) and other non-global ranges, and NAT64 / 6to4 forms of loopback; it now requires globally routable addresses. It also connects to the address it checked, closing the DNS-rebinding window described in 0.2.0's README.
- `batch` printed a traceback when `--out-dir` was a file or unwritable (now exit 2); `urlsplit` errors from bad bracketed hosts (`http://[::1`) no longer crash validation or `check` redirect handling; `... | head` no longer prints BrokenPipeError.
- `validate_campaign` accepts a prebuilt URL, so `batch` builds each link twice instead of three times (about 1.5x faster in the benchmark; noisy).

Added
- `utmkit check`: follow redirects and report dropped UTM parameters (public hosts only unless `--allow-private`).
- `--taxonomy rules.json` and `--fix`: naming-convention enforcement and normalisation.
- GA4 default-channel prediction (`gen`, `links.csv`, `ga4_unassigned` warning) based on Google's channel definitions; new warnings `no_medium`, `no_campaign` (CLI default, `--no-ga4` to disable; `validate_campaign(..., ga4=True)` in the API).
- `utm_id`, `utm_source_platform`, `utm_creative_format`, `utm_marketing_tactic` columns/fields.
- Cross-row checks: `case_variants`, `near_duplicate`, `duplicate_link`.
- New per-row checks: `bad_scheme`, `bad_url_chars`, `bad_value_chars`, `pre_encoded`, `overrides_existing`, `url_too_long`.
- Spec loader: `;` delimiter, header aliases, unknown-column warnings with did-you-mean; `load_spec()` API.
- `bench/bench.py` reproducible benchmark.

Changed (behaviour)
- The original query string is preserved byte-for-byte; values are percent-encoded with `%20` instead of `+`; custom `utm_*` keys are no longer dropped.
- Rows with an error finding are skipped by `batch` (previously an empty URL crashed the run and other errors were still built).
- `links.csv` has extra columns after `slug,final_url,qr`; cells that start with `=`, `+`, `-`, `@` are prefixed with `'`.
- Slugs: capped at 80 chars, Windows reserved names get `-link`, all-non-ASCII names get `link-<hash>` instead of `link`; numbering of colliding slugs no longer rescans (quadratic -> linear).
- `index.html` links only http(s) URLs and sets a CSP.
- Test fix: the "qr unavailable" test no longer fails when `qrcode` is installed.
