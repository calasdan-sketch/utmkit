"""0.2.0: byte-exact param preservation, GA4 checks, taxonomy, check, safety."""
import csv
import json
import random
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from utmkit.batch import load_spec, run_batch, write_csv
from utmkit.channels import ga4_channel
from utmkit.check import check_url
from utmkit.cli import main
from utmkit.core import (Campaign, build_url, existing_utm, sanitize, slugify,
                         validate_campaign, validate_rows)
from utmkit.taxonomy import check_taxonomy, fix_campaign, parse_taxonomy


# ---------- URL building ----------
@pytest.mark.parametrize("q", ["flag", "a=b%2Cc", "sig=a+b%3D%3D", "x=1;y=2", "p=%7Efoo/bar", "e=", "z=%E2%9C%93"])
def test_foreign_query_is_byte_exact(q):
    out = build_url(Campaign(f"https://ex.com/p?{q}#frag", source="s"))
    assert out.startswith(f"https://ex.com/p?{q}&utm_source=s") and out.endswith("#frag")


def test_fuzz_foreign_params_never_mutated():
    rnd = random.Random(7)
    alphabet = "abc012%+-_.~/;:,=*!'()"
    for _ in range(500):
        pairs = ["".join(rnd.choice(alphabet) for _ in range(rnd.randint(1, 8))) for _ in range(3)]
        pairs = [p for p in pairs if not p.lower().startswith("utm_")]
        q = "&".join(pairs)
        out = build_url(Campaign("https://ex.com/?" + q + "&utm_medium=old", source="s", medium="m"))
        assert out.startswith("https://ex.com/?" + q + "&utm_source=s")


def test_new_ga4_fields_and_custom_utm_survives():
    out = build_url(Campaign("https://ex.com/?utm_brand=x&UTM_ID=old", source="s", id="c9",
                             source_platform="Meta Ads"))
    assert "utm_brand=x" in out and "UTM_ID" not in out
    assert "utm_id=c9" in out and "utm_source_platform=Meta%20Ads" in out
    assert existing_utm("https://a.com/?utm_id=5&utm_source=A+b") == {"utm_id": "5", "utm_source": "A b"}


def test_value_encoding_of_reserved_chars():
    out = build_url(Campaign("https://ex.com", source="a&b=c#d", campaign="é"))
    assert "utm_source=a%26b%3Dc%23d" in out and "utm_campaign=%C3%A9" in out


# ---------- slugs ----------
def test_slug_non_latin_distinct_and_deterministic():
    a, b = slugify("Καλάς"), slugify("Άλφα")
    assert a != b and a.startswith("link-") and a == slugify("Καλάς")
    assert slugify("***") == "link"


def test_slug_long_and_reserved():
    s = slugify("x" * 500)
    assert len(s) <= 80 and s == slugify("x" * 500) and s != slugify("x" * 499)
    assert slugify("CON") == "con-link" and slugify("nul") == "nul-link" and slugify("com1") == "com1-link"
    assert slugify("console") == "console"


# ---------- validation ----------
def test_bad_scheme_is_error_and_row_skipped(tmp_path):
    rows = [(2, Campaign("javascript:alert(1)", source="a")),
            (3, Campaign("https://ok.com", source="a", medium="email", campaign="c")),
            (4, Campaign("", source="a"))]
    res = run_batch(rows, str(tmp_path / "o"), html_index=True)
    assert [r["url"] for r in res.rows] == ["https://ok.com"]
    codes = {f.code for f in res.findings}
    assert "bad_scheme" in codes and "no_url" in codes
    assert "javascript" not in (tmp_path / "o" / "index.html").read_text()


def test_data_and_file_scheme_rejected_but_host_port_is_not_scheme():
    assert any(f.code == "bad_scheme" for f in validate_campaign(Campaign("data:text/html,x", source="a")))
    assert any(f.code == "bad_scheme" for f in validate_campaign(Campaign("file:///etc/passwd", source="a")))
    codes = [f.code for f in validate_campaign(Campaign("localhost:8080/x", source="a"))]
    assert "bad_scheme" not in codes and "no_scheme" in codes


def test_control_and_bidi_chars_flagged_and_sanitized():
    f = validate_campaign(Campaign("https://a.com", source="x\x1b[31m", medium="email", campaign="c‮evil"))
    assert sum(1 for x in f if x.code == "bad_value_chars") == 2
    assert all("\x1b" not in x.detail and "‮" not in x.detail for x in f)
    assert sanitize("a​b\x00") == "a\\u200bb\\u0000"


def test_ga4_checks_are_opt_in_and_warn():
    c = Campaign("https://a.com", source="newsletter", medium="qr")
    assert not any(f.code.startswith("ga4") for f in validate_campaign(c))
    codes = [f.code for f in validate_campaign(c, ga4=True)]
    assert "ga4_unassigned" in codes and "no_campaign" in codes
    assert "no_medium" in [f.code for f in validate_campaign(Campaign("https://a.com", source="a"), ga4=True)]


def test_pre_encoded_overrides_and_long_url():
    codes = [f.code for f in validate_campaign(
        Campaign("https://a.com/?utm_source=old&p=" + "x" * 2100, source="spring%20sale", medium="email"))]
    assert {"pre_encoded", "overrides_existing", "url_too_long"} <= set(codes)


def test_cross_row_checks():
    rows = [(2, Campaign("https://a.com", source="Instagram", medium="paid-social", campaign="c")),
            (3, Campaign("https://b.com", source="instagram", medium="paid_social", campaign="c")),
            (4, Campaign("https://a.com", source="Instagram", medium="paid-social", campaign="c"))]
    got = {f.code for f in validate_rows(rows)}
    assert got == {"case_variants", "near_duplicate", "duplicate_link"}
    assert validate_rows([(2, Campaign("https://a.com", source="a"))]) == []


# ---------- GA4 channels (rules from Google's help page) ----------
@pytest.mark.parametrize("src,med,camp,want", [
    ("(direct)", "(none)", "", "Direct"),
    ("google", "cpc", "", "Paid Search"),
    ("Google", "CPC", "", "Paid Search"),
    ("facebook", "paid-social", "", "Paid Social"),
    ("youtube", "cpv-paid", "", "Paid Video"),
    ("x", "cpm", "", "Display"),
    ("someads", "ppc", "", "Paid Other"),
    ("newsletter", "email", "", "Email"),
    ("E-Mail", "x", "", "Email"),
    ("instagram", "social", "", "Organic Social"),
    ("foo", "social-media", "", "Organic Social"),
    ("foo", "organic", "", "Organic Search"),
    ("foo", "affiliate", "", "Affiliates"),
    ("foo", "referral", "", "Referral"),
    ("foo", "audio", "", "Audio"),
    ("sms", "x", "", "SMS"),
    ("foo", "app-push", "", "Mobile Push Notifications"),
    ("foo", "qr", "", "Unassigned"),
    ("foo", "print", "", "Unassigned"),
    ("google", "cpc", "my cross-network", "Cross-network"),
    ("foo", "paid", "summer shopping", "Paid Shopping"),
])
def test_ga4_channel_rules(src, med, camp, want):
    assert ga4_channel(src, med, camp).name == want


def test_paid_other_is_flagged_uncertain():
    assert not ga4_channel("someads", "cpc").certain and ga4_channel("google", "cpc").certain


# ---------- spec loading ----------
def test_loader_aliases_semicolon_unknown_columns(tmp_path):
    p = tmp_path / "s.csv"
    p.write_bytes("﻿Landing Page;UTM Source;utm_medium;campain;utm_id\n"
                  "https://a.com;ig;social;c;77\n;;;;\n".encode("utf-8"))
    rows, findings = load_spec(str(p))
    assert len(rows) == 1 and rows[0][1].source == "ig" and rows[0][1].id == "77"
    f = [x for x in findings if x.code == "unknown_column"]
    assert len(f) == 1 and "campaign" in f[0].detail


def test_loader_rejects_bad_files(tmp_path):
    p = tmp_path / "s.csv"
    p.write_text("source\nx\n")
    with pytest.raises(ValueError, match="url"):
        load_spec(str(p))
    p.write_text("url,source,utm_source\nhttps://a.com,a,b\n")
    with pytest.raises(ValueError, match="two columns"):
        load_spec(str(p))
    p.write_bytes(b"url\n\xff\xfe\n")
    with pytest.raises(ValueError, match="UTF-8"):
        load_spec(str(p))
    p.write_text("")
    with pytest.raises(ValueError, match="empty"):
        load_spec(str(p))
    p.write_text("url\n" + '"' + "x" * 200000 + '"\n')
    with pytest.raises(ValueError, match="malformed"):
        load_spec(str(p))


# ---------- taxonomy ----------
TAX = {"fields": {"source": {"allowed": ["instagram", "newsletter"], "aliases": {"ig": "instagram"}},
                  "medium": {"allowed": ["social", "email"]},
                  "campaign": {"pattern": "[a-z0-9]+-[0-9]{2}", "max_length": 20}},
       "required": ["source", "medium", "campaign"]}


def test_taxonomy_checks_and_fix():
    tax = parse_taxonomy(TAX)
    bad = Campaign("https://a.com", source="IG", medium="Social Media", campaign="Launch 26")
    found = {f.code for f in check_taxonomy(bad, tax, "r")}
    assert {"taxonomy_not_allowed", "taxonomy_pattern"} <= found
    fixed, changes = fix_campaign(bad, tax)
    assert (fixed.source, fixed.campaign) == ("instagram", "launch-26") and changes
    assert fixed.medium == "social-media"
    ok = Campaign("https://a.com", source="instagram", medium="social", campaign="launch-26")
    assert check_taxonomy(ok, tax, "r") == []
    missing = Campaign("https://a.com", source="instagram")
    assert [f.code for f in check_taxonomy(missing, tax, "r")].count("taxonomy_required") == 2


def test_taxonomy_regex_is_not_run_on_huge_values():
    tax = parse_taxonomy({"fields": {"campaign": {"pattern": "(a+)+$"}}})
    out = check_taxonomy(Campaign("https://a.com", campaign="a" * 100000 + "!"), tax, "r")
    assert out and out[0].code == "taxonomy_pattern"


@pytest.mark.parametrize("bad", [[], {"x": 1}, {"fields": {"nope": {}}}, {"fields": {"source": {"allow": []}}},
                                 {"fields": {"source": {"pattern": "("}}}, {"required": ["nope"]},
                                 {"fields": {"source": {"allowed": "x"}}},
                                 {"fields": {"source": {"max_length": 0}}}])
def test_bad_taxonomy_fails_closed(bad):
    with pytest.raises(ValueError):
        parse_taxonomy(bad)


# ---------- batch output ----------
def test_links_csv_columns_and_formula_injection(tmp_path):
    rows = [(2, Campaign("https://a.com", source="a", medium="email", campaign="=HYPERLINK(1)", name="n"))]
    res = run_batch(rows, str(tmp_path / "o"))
    write_csv(res, str(tmp_path / "o" / "links.csv"))
    with open(tmp_path / "o" / "links.csv", encoding="utf-8") as fh:
        got = list(csv.DictReader(fh))[0]
    assert list(got)[:3] == ["slug", "final_url", "qr"]  # old columns first
    assert got["utm_campaign"].startswith("'=") and got["ga4_channel"] == "Email"


def test_fix_flag_in_batch(tmp_path):
    rows = [(2, Campaign("https://a.com", source="Instagram", medium="Social", campaign="Big Sale"))]
    res = run_batch(rows, str(tmp_path / "o"), fix=True)
    assert "utm_campaign=big-sale" in res.rows[0]["final_url"]
    assert any(f.code == "fixed" and f.severity == "info" for f in res.findings)


def test_large_batch_slugs_are_fast(tmp_path):
    rows = [(i, Campaign(f"https://a.com/{i}", source="a", medium="email", campaign="c", name="same"))
            for i in range(3000)]
    res = run_batch(rows, str(tmp_path / "o"))
    assert len({r["slug"] for r in res.rows}) == 3000


# ---------- redirect check ----------
class _H(BaseHTTPRequestHandler):
    def do_HEAD(self):  # noqa: N802
        p = self.path
        if p.startswith("/keep"):
            self.send_response(302); self.send_header("Location", "/final?" + p.split("?", 1)[1])  # noqa: E702
        elif p.startswith("/drop"):
            self.send_response(301); self.send_header("Location", "/final")  # noqa: E702
        elif p.startswith("/loop"):
            self.send_response(302); self.send_header("Location", "/loop")  # noqa: E702
        elif p.startswith("/evil"):
            self.send_response(302); self.send_header("Location", "file:///etc/passwd")  # noqa: E702
        elif p.startswith("/nohead"):
            self.send_response(405)
        else:
            self.send_response(200)
        self.end_headers()

    def do_GET(self):  # noqa: N802
        self.do_HEAD() if not self.path.startswith("/nohead") else (self.send_response(200), self.end_headers())

    def log_message(self, *a):
        pass


@pytest.fixture
def server():
    srv = HTTPServer(("127.0.0.1", 0), _H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield "http://127.0.0.1:%d" % srv.server_port
    srv.shutdown()


def test_check_redirect_outcomes(server):
    q = "?utm_source=a&utm_medium=b"
    assert check_url(server + "/keep" + q, allow_private=True).ok
    r = check_url(server + "/drop" + q, allow_private=True)
    assert not r.ok and r.lost == ["utm_medium", "utm_source"] and "dropped" in r.problem
    assert "redirects" in check_url(server + "/loop" + q, allow_private=True, max_hops=3).problem
    assert "non-http" in check_url(server + "/evil" + q, allow_private=True).problem
    assert check_url(server + "/nohead" + q, allow_private=True).ok  # HEAD 405 -> GET


def test_check_refuses_private_by_default(server):
    r = check_url(server + "/keep?utm_source=a")
    assert not r.ok and "non-public" in r.problem
    assert not check_url("file:///etc/passwd").ok
    assert "refusing" in check_url("ftp://x.com/").problem


def test_check_cli(server, tmp_path, capsys):
    p = tmp_path / "s.csv"
    p.write_text("url,source,medium,campaign\n%s/keep,a,email,c\n%s/drop,a,email,c\n" % (server, server))
    assert main(["check", str(p), "--allow-private"]) == 1
    out = capsys.readouterr().out
    assert "OK    row 2" in out and "FAIL  row 3" in out and "1/2" in out
    assert main(["check", str(p)]) == 1  # private refused


# ---------- CLI ----------
def test_cli_batch_taxonomy_and_exit_codes(tmp_path, capsys):
    spec = tmp_path / "s.csv"
    spec.write_text("url,source,medium,campaign,name\nhttps://a.com,Instagram,social,launch-26,A\n"
                    "https://b.com,tiktok,social,launch-26,B\n")
    tax = tmp_path / "t.json"
    tax.write_text(json.dumps(TAX))
    assert main(["batch", str(spec), "--out-dir", str(tmp_path / "o"), "--taxonomy", str(tax)]) == 1
    err = capsys.readouterr().err
    assert "taxonomy_not_allowed" in err
    assert main(["batch", str(spec), "--out-dir", str(tmp_path / "o2"), "--taxonomy", str(tax), "--fix"]) == 1
    tax.write_text("{")
    assert main(["validate", str(spec), "--taxonomy", str(tax)]) == 2


def test_cli_gen_reports_channel(capsys):
    assert main(["gen", "https://a.com", "--source", "google", "--medium", "cpc", "--campaign", "c"]) == 0
    cap = capsys.readouterr()
    assert "utm_source=google" in cap.out and "Paid Search" in cap.err


def test_cli_validate_strict_ignores_info_and_sanitizes(tmp_path, capsys):
    spec = tmp_path / "s.csv"
    spec.write_text("url,source,medium,campaign,name\nhttps://a.com,a,email,c,\x1b[2Jboom\n")
    assert main(["validate", str(spec), "--strict"]) == 0
    assert "\x1b" not in capsys.readouterr().out


def test_check_refuses_ipv4_mapped_loopback():
    r = check_url("http://[::ffff:127.0.0.1]:9/x?utm_source=a")
    assert not r.ok and "non-public" in r.problem
