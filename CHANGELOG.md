# Changelog

## 0.2.0 (unreleased)

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
