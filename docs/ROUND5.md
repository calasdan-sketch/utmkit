# Round 5 (utmkit)

Branch `expert-2`, owner Calas Automations Inc. No sub-agents were available, so the specialists below were played in sequence; every finding names the command that proved it. Round 4's `docs/ROUND4.md` was absent, so a packaging first-hour pass was done first (section 0).

## 0. Packaging first-hour pass (offline)

| Check | Command | Result |
|---|---|---|
| Build sdist + wheel from a clean copy | `python -m build --outdir <scratch>/dist .` | ok |
| Metadata valid | `twine check dist/*` | PASSED both |
| Wheel contents | `unzip -l dist/*.whl` | 10 modules + `py.typed` + LICENSE + METADATA; no tests, no junk |
| sdist contents | `tar tzf dist/*.tar.gz` | was missing tests/golden and CHANGELOG; fixed with `MANIFEST.in` |
| Author shipped | `unzip -p dist/*.whl "*/METADATA" \| head` | `Author: Calas Automations Inc.` and `Maintainer: ...` |
| Fresh non-editable install, README quick start | venv + `pip install dist/*.whl`; `utmkit gen`, `batch --html`, `audit` from a folder with a space in its name | ok on Python 3.13 and 3.11 |
| Full suite on 3.11 | `python3.11 -m pytest` | 198 passed (then 199 after one more test) |
| Dependencies | `pip list` in clean venv | none beyond utmkit (qrcode is the optional extra) |
| Registry | `curl https://pypi.org/pypi/utmkit/json` | 404, so unpublished; release 0.2.0, no bump |
| Not tested | Python 3.9 and 3.10 (not installed), Windows | CI declares 3.9 |

Defects: `license = "MIT"` needs setuptools 77 but `requires` said 68 (fixed); no `py.typed` (added); `pytest` failed to import the package unless installed (pytest `pythonpath` added); `check` sent a hard-coded `utmkit-check/0.2` User-Agent (now the real version).

## 1. Specialists

**Paid-media manager (Google Ads / Meta).** Ran `utmkit gen ... --campaign '{campaignid}'`: the output was `utm_campaign=%7Bcampaignid%7D`, which Google Ads/Meta do not substitute, so every click would report the literal text. Fixed: placeholders are kept raw (`encode_value`), exempt from case/space/GA4-guess/taxonomy/`--fix`, noted as `info`, and already-published encoded ones are flagged by `audit`. Proof: `tests/test_round5.py::test_placeholders_survive_unencoded` (6 forms), bench line "ad-platform placeholders kept unencoded 1/8 -> 8/8". Also: `check` on a templated link would have requested a URL with braces; it now substitutes `test`.

**Marketing-analytics / GA4 specialist.** (a) Table test of every documented medium rule of the default channel group (19 cases); a mutation that dropped the `link` referral medium survived the old suite, now killed. (b) Placeholders in source/medium made `ga4_unassigned` fire falsely; suppressed and `links.csv` shows an empty channel instead of a guess. (c) Re-fetched Google's utm help page on 2026-11-08: `utm_marketing_tactic` still listed. Not changed: the channel source lists remain partial (documented).

**URL-parsing / security engineer.** `urlsplit("https://evil.example\\@good.example/").hostname` is `good.example`, but browsers treat `\` as `/` and go to `evil.example`; `check` would have vetted one host and the link points to another. Now an error (`backslash_in_url`, only before `?`/`#`), `check` refuses it and any redirect to one. `?a=1&amp;utm_source=x` (copied from HTML) produced a doubled `utm_source`; now error `html_entity_in_url`. `user:pw@host` URLs warn (`url_credentials`, secret not echoed); non-ASCII host is `idn_host` info. `gen --source $'\xff'` raised `UnicodeEncodeError`: lone surrogates are now `bad_value_chars` and `build_url` raises `ValueError`. `PYTHONIOENCODING=ascii utmkit gen 'https://ex.com/é' ...` raised a traceback; output now uses backslash escapes. Huge input: 100,000 rows validate; 3 MB cell refused by the CSV reader with a plain message; a 100k-character value takes about 3 s (Python's `unquote`), documented.

**CI / DevOps integrator.** Wanted inline annotations for a spec CSV in a repo: added `--format github` (escaped; injection test with `\n::error::` in a finding). CI now installs `.[dev]` and asserts the wheel's author line.

**QA / test-methodology expert.** Added hypothesis property tests (round-trip of every utm value through `existing_utm`, idempotent rebuild, foreign query untouched, slugs filesystem-safe, `sanitize` leaves nothing dangerous, `validate_campaign` never raises; 300 examples each), golden files for text/json/github validate, audit json, batch json, `links.csv`, `index.html`, `taxonomy-init`, and `bench/mutants.py` (15 hand-picked mutants; 14 killed at first run, the survivor drove the GA4 table test; all killed after).

**Competitor maintainer (re-checked read-only 2026-11-08).** npm `utm-builder` latest is still 0.0.1, `utm-cli` 1.0.0 (registry JSON); Google Campaign URL Builder not re-readable (client-rendered), UTM.io / Terminus not tested. Nothing found that changes the README comparison.

Upgrade-path test from the registry: skipped as instructed (and nothing is published).

## 2. Scored ideas (value / differentiation / effort / risk, 1-5; effort and risk lower is better)

| # | Idea | Value | Diff | Effort | Risk | Status |
|---|---|---|---|---|---|---|
| 1 | Keep ad-platform placeholders unencoded | 5 | 5 | 2 | 2 | DONE |
| 2 | Refuse backslash host-confusion URLs | 4 | 4 | 1 | 1 | DONE |
| 3 | `&amp;` copied from HTML | 4 | 4 | 1 | 1 | DONE |
| 4 | GitHub Actions annotations | 4 | 4 | 2 | 1 | DONE |
| 5 | Credentials in URL warning | 3 | 3 | 1 | 1 | DONE |
| 6 | Surrogate / non-UTF-8 argv crash | 3 | 2 | 1 | 1 | DONE |
| 7 | ASCII terminal traceback | 3 | 2 | 1 | 1 | DONE |
| 8 | Property-based + golden + mutation tests | 4 | 2 | 3 | 1 | DONE |
| 9 | `py.typed`, mypy clean, MANIFEST for sdist tests | 2 | 1 | 1 | 1 | DONE |
| 10 | IDN host info | 2 | 3 | 1 | 1 | DONE |
| 11 | SARIF output | 3 | 3 | 3 | 2 | NOT-DONE (annotations cover GitHub; no other consumer asked) |
| 12 | JUnit XML | 2 | 2 | 2 | 1 | NOT-DONE |
| 13 | Warn "social + paid-looking campaign": GA4 files it as Organic Social, not Paid | 4 | 5 | 3 | 3 | NOT-DONE (needs a user-supplied `paid` column; cannot be guessed) |
| 14 | Google Ads auto-tagging (gclid) vs manual UTM conflict note | 3 | 4 | 2 | 3 | NOT-DONE (depends on an account setting utmkit cannot see) |
| 15 | Platform URL length limits table | 3 | 3 | 2 | 4 | NOT-DONE (limits unverified; 2000 rule kept) |
| 16 | Complete GA4 source lists (search/social/video/shopping) | 4 | 3 | 4 | 3 | NOT-DONE (Google's lists are long and change) |
| 17 | `--format csv` of findings for spreadsheets | 2 | 2 | 1 | 1 | NOT-DONE |
| 18 | Redirect check via GET fallback for meta-refresh | 2 | 3 | 4 | 3 | NOT-DONE |
| 19 | Short-link (bit.ly style) generation | 3 | 2 | 5 | 5 | NOT-DONE (needs paid/live services) |
| 20 | MCP server so agents can validate links | 3 | 4 | 3 | 2 | NOT-DONE |
| 21 | Pre-commit hook config | 2 | 2 | 1 | 1 | NOT-DONE |
| 22 | Per-platform macro list with docs links | 3 | 4 | 3 | 3 | NOT-DONE (needs each platform's current docs) |
| 23 | Windows run in CI | 3 | 1 | 1 | 1 | NOT-DONE (add `windows-latest` to the CI matrix; never run here) |

## 3. What I could not test

- Windows, Python 3.9 and 3.10; 3.12 only partly. GitHub Actions rendering of the annotations (only the text is pinned by golden files).
- The macro shapes other than `{keyword}`/`{lpurl}` against each platform's live docs (Google's help page is client-rendered; `{campaignid}`, Meta `{{...}}`, `__X__` are from memory).
- Real redirect checks over the network (all tests mock the fetch; the pinned-TLS path was only ever hand-tested).
- Benchmark numbers on a quiet machine: the shared host had a load average above 30 during the run, so throughput figures are low and noisy; relative rows (fidelity, detection, placeholders) are deterministic. Same-time A/B of throughput, round-3 code vs this tree: 3335/4078/3739 vs 2586 (before an optimisation of the new checks) and 3711 (after), rows/s; cost of the round-5 checks is about 0-10%.
- Upgrade from a published version: nothing is published.
