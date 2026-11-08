"""Round 5: author pin, ad-platform placeholders, URL-parser hostile cases, GitHub annotations,
golden files for every output format, property-based tests."""
import os
import re

import pytest

import utmkit
from utmkit import Campaign, build_url
from utmkit.cli import github_annotation, main
from utmkit.core import (Finding, sanitize, validate_campaign)
from utmkit.check import check_url
from utmkit.taxonomy import fix_campaign, parse_taxonomy, check_taxonomy

ROOT = os.path.dirname(os.path.dirname(__file__))
GOLDEN = os.path.join(os.path.dirname(__file__), "golden")
AUTHOR = "Calas Automations Inc."


def _read(name):
    with open(os.path.join(ROOT, name), encoding="utf-8") as fh:
        return fh.read()


# ---- author line ---------------------------------------------------------------------------
def test_author_string_is_pinned_everywhere():
    assert utmkit.__author__ == AUTHOR
    py = _read("pyproject.toml")
    assert re.search(r'authors\s*=\s*\[\{\s*name\s*=\s*"Calas Automations Inc\."\s*\}\]', py)
    assert re.search(r'maintainers\s*=\s*\[\{\s*name\s*=\s*"Calas Automations Inc\."\s*\}\]', py)
    assert f"Copyright (c) 2026 {AUTHOR}" in _read("LICENSE")
    assert AUTHOR in _read("README.md")
    for old in ("calasdan-sketch", "Dan Calas"):
        assert old not in py and old not in _read("LICENSE")


def test_version_consistent_and_printed(capsys):
    m = re.search(r'^version\s*=\s*"([^"]+)"', _read("pyproject.toml"), re.M)
    assert m and m.group(1) == utmkit.__version__
    assert f"## {utmkit.__version__}" in _read("CHANGELOG.md")
    with pytest.raises(SystemExit):
        main(["--version"])
    out = capsys.readouterr().out
    assert utmkit.__version__ in out and AUTHOR in out


def test_no_email_invented_in_metadata():
    assert "email" not in _read("pyproject.toml").lower().split("[project.scripts]")[0]


# ---- placeholders (paid media) -------------------------------------------------------------
@pytest.mark.parametrize("val", ["{campaignid}", "{{campaign.name}}", "{ifmobile:m}", "__CAMPAIGN_NAME__",
                                 "{keyword}-x", "a-{adgroupid}"])
def test_placeholders_survive_unencoded(val):
    url = build_url(Campaign("https://ex.com/", source="s", campaign=val))
    assert f"utm_campaign={val}" in url
    assert "%7B" not in url


def test_text_around_placeholder_is_still_encoded():
    url = build_url(Campaign("https://ex.com/", source="s", term="red shoes {keyword}&x"))
    assert "utm_term=red%20shoes%20{keyword}%26x" in url


def test_malformed_braces_are_encoded():
    url = build_url(Campaign("https://ex.com/", source="s", term="{ not a macro }"))
    assert "%7B" in url


def test_placeholder_not_flagged_as_case_or_unassigned():
    c = Campaign("https://ex.com/", source="google", medium="{Medium}", campaign="{CampaignId}")
    codes = {f.code for f in validate_campaign(c, ga4=True)}
    assert "not_lowercase" not in codes and "ga4_unassigned" not in codes
    assert "placeholder" in codes


def test_placeholder_info_does_not_fail_strict(tmp_path, capsys):
    spec = tmp_path / "s.csv"
    spec.write_text("url,source,medium,campaign\nhttps://ex.com/,google,cpc,{campaignid}\n")
    assert main(["validate", str(spec), "--strict"]) == 0


def test_audit_flags_already_encoded_placeholder():
    c = Campaign("https://ex.com/?utm_source=google&utm_campaign=%7Bcampaignid%7D", source="google",
                 campaign="{campaignid}")
    assert "placeholder_encoded" in {f.code for f in validate_campaign(c)}
    assert "%7B" not in build_url(c)  # rebuilding repairs it


def test_fix_keeps_placeholder_case_and_lowercases_rest():
    c, changes = fix_campaign(Campaign("https://ex.com/", source="S", campaign="Spring {CampaignId} Sale"))
    assert c.campaign == "spring-{CampaignId}-sale" and c.source == "s"


def test_taxonomy_does_not_reject_placeholders():
    tax = parse_taxonomy({"fields": {"campaign": {"allowed": ["a"]}}})
    assert check_taxonomy(Campaign("https://ex.com/", source="s", campaign="{campaignid}"), tax, "x") == []
    assert check_taxonomy(Campaign("https://ex.com/", source="s", campaign="b"), tax, "x")


def test_check_substitutes_placeholders(tmp_path, monkeypatch, capsys):
    seen = []

    def fake(urls, allow_private, timeout=10, workers=8):
        seen.extend(urls)
        from utmkit.check import CheckResult
        return [CheckResult(url=u, ok=True, status=200, hops=[u]) for u in urls]
    monkeypatch.setattr("utmkit.check.check_many", fake)
    spec = tmp_path / "s.csv"
    spec.write_text("url,source,medium,campaign\nhttps://ex.com/,google,cpc,{campaignid}\n")
    assert main(["check", str(spec)]) == 0
    assert seen and "{" not in seen[0] and "utm_campaign=test" in seen[0]


# ---- hostile URLs --------------------------------------------------------------------------
def _codes(url, **kw):
    return {f.code: f.severity for f in validate_campaign(Campaign(url, source="s", **kw), ga4=True)}


def test_html_entity_ampersand_is_an_error():
    assert _codes("https://ex.com/?a=1&amp;utm_source=x")["html_entity_in_url"] == "error"
    assert "html_entity_in_url" not in _codes("https://ex.com/?a=1&b=2")


def test_backslash_url_is_an_error_and_never_checked():
    assert _codes("https://evil.example\\@good.example/")["backslash_in_url"] == "error"
    called = []
    res = check_url("https://evil.example\\@good.example/", allow_private=True,
                    fetch=lambda u, t: called.append(u) or (200, ""))
    assert not res.ok and not called


def test_redirect_to_backslash_url_refused():
    def fetch(u, t):
        return (302, "https://evil.example\\@good.example/?utm_source=s") if "start" in u else (200, "")
    res = check_url("https://127.0.0.1/start?utm_source=s", allow_private=True, fetch=fetch)
    assert not res.ok and "backslash" in res.problem


def test_userinfo_warns_without_echoing_secret():
    f = [x for x in validate_campaign(Campaign("https://user:pw9@ex.com/", source="s")) if x.code == "url_credentials"]
    assert f and "pw9" not in f[0].detail


def test_idn_host_is_info():
    assert _codes("https://пример.example/")["idn_host"] == "info"


def test_lone_surrogate_never_crashes(capsys):
    c = Campaign("https://ex.com/", source="a\udcff")
    assert any(f.code == "bad_value_chars" for f in validate_campaign(c))
    with pytest.raises(ValueError):
        build_url(c)
    assert "\\udcff" in sanitize("a\udcff")


def test_gen_with_undecodable_argument_is_a_clean_error(capsys):
    assert main(["gen", "https://ex.com/", "--source", "a\udcff"]) == 1
    assert "Traceback" not in capsys.readouterr().err


# ---- GitHub annotations --------------------------------------------------------------------
def test_github_annotation_escapes_injection():
    line = github_annotation(Finding("error", "x", "row 7", "bad\n::error::pwned\r%"), "dir,a:b/spec.csv")
    assert "\n" not in line and "\r" not in line
    assert line.startswith("::error file=dir%2Ca%3Ab/spec.csv,line=7,title=utmkit x::")
    assert "\\u000a::error::pwned\\u000d%25" in line


def test_github_levels():
    assert github_annotation(Finding("warn", "c", "all rows", "m"), "f").startswith("::warning file=f,title=")
    assert github_annotation(Finding("info", "c", "row 2", "m"), "f").startswith("::notice ")


# ---- golden files --------------------------------------------------------------------------
def _golden(name, text):
    path = os.path.join(GOLDEN, name)
    if os.environ.get("UPDATE_GOLDEN"):
        with open(path, "w", encoding="utf-8", newline="") as fh:
            fh.write(text)
    with open(path, encoding="utf-8", newline="") as fh:
        assert text == fh.read(), f"{name} differs; rerun with UPDATE_GOLDEN=1 and review the diff"


@pytest.fixture
def golden_cwd(monkeypatch):
    monkeypatch.chdir(GOLDEN)


@pytest.mark.parametrize("fmt", ["json", "github", "text"])
def test_golden_validate(fmt, golden_cwd, capsys):
    rc = main(["validate", "spec.csv", "--format", fmt])
    _golden(f"validate.{fmt}.txt", f"exit={rc}\n" + capsys.readouterr().out)


def test_golden_audit_json(golden_cwd, capsys):
    rc = main(["audit", "urls.txt", "--format", "json"])
    _golden("audit.json.txt", f"exit={rc}\n" + capsys.readouterr().out)


def test_golden_batch_outputs(tmp_path, golden_cwd, capsys):
    out = tmp_path / "out"
    rc = main(["batch", "spec.csv", "--out-dir", str(out), "--html", "--format", "json"])
    stdout = capsys.readouterr().out.replace(str(out), "<OUT>")
    _golden("batch.json.txt", f"exit={rc}\n" + stdout)
    _golden("links.csv.txt", (out / "links.csv").read_text(encoding="utf-8"))
    _golden("index.html.txt", (out / "index.html").read_text(encoding="utf-8"))


def test_golden_taxonomy_init(golden_cwd, capsys):
    rc = main(["taxonomy-init", "spec.csv"])
    _golden("taxonomy-init.json.txt", f"exit={rc}\n" + capsys.readouterr().out)


# ---- GA4 channel rules, one case per documented medium rule (kills a mutant that dropped 'link')
@pytest.mark.parametrize("source,medium,expected", [
    ("google", "cpc", "Paid Search"), ("facebook", "paid-social", "Paid Social"),
    ("youtube", "cpv", "Paid Video"), ("amazon", "cpc", "Paid Shopping"),
    ("x", "display", "Display"), ("x", "banner", "Display"),
    ("x", "referral", "Referral"), ("x", "app", "Referral"), ("x", "link", "Referral"),
    ("x", "affiliate", "Affiliates"), ("x", "audio", "Audio"), ("x", "sms", "SMS"),
    ("x", "push", "Mobile Push Notifications"), ("x", "email", "Email"), ("x", "e-mail", "Email"),
    ("(direct)", "(none)", "Direct"), ("google", "organic", "Organic Search"),
    ("instagram", "social", "Organic Social"), ("x", "qr", "Unassigned"),
])
def test_ga4_default_channel_table(source, medium, expected):
    from utmkit.channels import ga4_channel
    assert ga4_channel(source, medium).name == expected


def test_ascii_terminal_does_not_crash():
    import subprocess
    import sys
    env = dict(os.environ, PYTHONIOENCODING="ascii", PYTHONPATH=os.path.join(ROOT, "src"))
    r = subprocess.run([sys.executable, "-m", "utmkit.cli", "gen", "https://ex.com/é", "--source", "s"],
                       capture_output=True, text=True, env=env, cwd=ROOT)
    assert r.returncode == 0 and "Traceback" not in r.stderr
    assert "\\xe9" in r.stdout


def test_backslash_in_query_is_not_an_error():
    assert "backslash_in_url" not in _codes("https://ex.com/p?path=a\\b")
    assert "backslash_in_url" in _codes("https://ex.com\\evil/p")
    assert "backslash_in_url" in _codes("https://ex.com/a\\b")
