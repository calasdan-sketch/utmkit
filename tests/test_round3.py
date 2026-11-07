import time

import pytest

from utmkit.check import _host_allowed, check_url
from utmkit.taxonomy import parse_taxonomy, safe_pattern


@pytest.mark.parametrize("pat", ["(a+)+$", "(a*)*", "(a|aa)+", "(a|ab)*", "([a-z]+-?)+", "(x+x+)+y",
                                 "(.*a){12}", "(a?){30}a{30}", "a" * 400])
def test_redos_patterns_rejected_at_load(pat):
    assert not safe_pattern(pat)
    with pytest.raises(ValueError):
        parse_taxonomy({"fields": {"campaign": {"pattern": pat}}})


@pytest.mark.parametrize("pat", ["[a-z0-9]+-[0-9]{2}", "(email|social)+", "[a-z]+(-[a-z]+)*",
                                 "[a-z0-9]+(_[a-z0-9]+)*", "launch-[0-9]{4}"])
def test_ordinary_patterns_still_allowed_and_fast(pat):
    tax = parse_taxonomy({"fields": {"campaign": {"pattern": pat}}})
    t = time.time()
    tax.fields["campaign"].pattern.fullmatch("a-" * 90 + "!")
    assert time.time() - t < 1


@pytest.mark.parametrize("host", ["100.64.0.1", "100.127.255.254", "192.0.0.8", "198.18.0.1",
                                  "2002:7f00:1::", "64:ff9b::7f00:1", "::ffff:10.0.0.1", "240.0.0.1"])
def test_non_global_addresses_refused(host):
    assert _host_allowed(host, 80, False)


# ---- check: pinned connection, hop reporting -------------------------------------------------
import http.server
import json
import threading

from utmkit.batch import load_spec, load_urls
from utmkit.cli import main
from utmkit.core import Campaign, campaign_from_url, build_url, validate_campaign
from utmkit.history import check_history, load_history
from utmkit.taxonomy import suggest_taxonomy


class _H(http.server.BaseHTTPRequestHandler):
    def do_HEAD(self):
        if self.path.startswith("/short"):
            self.send_response(302)
            self.send_header("Location", "/mid?utm_source=a&utm_medium=b")
        elif self.path.startswith("/mid"):
            self.send_response(302)
            self.send_header("Location", "/land")
        elif self.path.startswith("/rewrite"):
            self.send_response(302)
            self.send_header("Location", "/land?utm_source=OTHER")
        else:
            self.send_response(200)
        self.end_headers()

    def log_message(self, *a):
        pass


@pytest.fixture(scope="module")
def server():
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


def test_check_refuses_loopback_by_default(server):
    r = check_url(server + "/land?utm_source=a")
    assert not r.ok and "non-public" in r.problem


def test_check_reports_hop_where_tags_were_lost(server):
    r = check_url(server + "/short?utm_source=a&utm_medium=b&utm_campaign=c", allow_private=True)
    assert not r.ok and r.lost == ["utm_campaign", "utm_medium", "utm_source"]
    assert r.lost_at == 1 and "first lost at hop 1" in r.problem


def test_check_reports_rewritten_value(server):
    r = check_url(server + "/rewrite?utm_source=a", allow_private=True)
    assert not r.ok and r.changed == ["utm_source"] and "rewrote" in r.problem


def test_check_ok_path(server):
    r = check_url(server + "/land?utm_source=a", allow_private=True)
    assert r.ok and r.status == 200


def test_check_malformed_redirect_target_does_not_crash():
    r = check_url("http://example.invalid/?utm_source=a", allow_private=True,
                  fetch=lambda u, t: (302, "http://x:99999999/"))
    assert not r.ok and "malformed" in r.problem


# ---- validation ------------------------------------------------------------------------------
@pytest.mark.parametrize("url", ["https://ex.com:abc/", "https:///x", "http://[::1", "https://ex.com:99999/"])
def test_bad_host_is_an_error(url):
    f = validate_campaign(Campaign(url, source="s"))
    assert [x.code for x in f] == ["bad_host"] and f[0].severity == "error"


def test_good_hosts_still_fine():
    for u in ("https://ex.com:8443/", "http://[::1]:80/", "https://user@ex.com/"):
        assert not [x for x in validate_campaign(Campaign(u, source="s")) if x.severity == "error"]


def test_email_in_value_is_flagged_not_blocked():
    f = validate_campaign(Campaign("https://e.com", source="s", content="joe@example.com"))
    assert [x.code for x in f] == ["pii_email"] and f[0].severity == "warn"
    assert not validate_campaign(Campaign("https://e.com", source="s", content="a-b"))


def test_campaign_from_url_roundtrip():
    u = "https://e.com/p?a=1&utm_source=x&utm_medium=Email%20x&utm_id=7"
    c = campaign_from_url(u)
    assert (c.source, c.medium, c.id) == ("x", "Email x", "7")
    assert build_url(c).split("?")[1].split("&")[0] == "a=1"


# ---- spec loading, audit, history, taxonomy-init, json ---------------------------------------
def test_tab_delimited_spec(tmp_path):
    p = tmp_path / "s.tsv"
    p.write_text("url\tsource\tmedium\tcampaign\nhttps://e.com\ts\temail\tc\n", encoding="utf-8")
    rows, _ = load_spec(str(p))
    assert rows[0][1].medium == "email" and rows[0][1].campaign == "c"


def test_load_urls_plain_list_and_csv(tmp_path):
    p = tmp_path / "u.txt"
    p.write_text("# c\nhttps://e.com/a?utm_source=x&utm_medium=m\n\nhttps://e.com/b\n")
    rows, _ = load_urls(str(p))
    assert [n for n, _ in rows] == [2, 4] and rows[0][1].source == "x"
    q = tmp_path / "u.csv"
    q.write_text("url,source\nhttps://e.com/a?utm_source=x&utm_medium=m,override\n")
    rows, _ = load_urls(str(q))
    assert rows[0][1].source == "override" and rows[0][1].medium == "m"


def test_audit_cli(tmp_path, capsys):
    p = tmp_path / "u.txt"
    p.write_text("https://e.com/a?utm_source=Ig&utm_medium=social&utm_campaign=c\nhttps://e.com/b\n")
    rc = main(["audit", str(p), "--format", "json"])
    doc = json.loads(capsys.readouterr().out)
    codes = {(f["code"], f["where"]) for f in doc["findings"]}
    assert rc == 1 and ("untagged", "row 2") in codes and ("not_lowercase", "row 1") in codes


def test_json_output_escapes_control_and_bidi(tmp_path, capsys):
    p = tmp_path / "s.csv"
    p.write_text("url,source,medium,campaign\nhttps://e.com,x\u202eevil\x1b[31m,email,c\n", encoding="utf-8")
    main(["validate", str(p), "--format", "json"])
    out = capsys.readouterr().out
    assert "\u202e" not in out and "\x1b" not in out
    json.loads(out)


def test_batch_json_output(tmp_path, capsys):
    p = tmp_path / "s.csv"
    p.write_text("url,source,medium,campaign\nhttps://e.com,x,email,c\nnotaurl:///,x,y,z\n")
    rc = main(["batch", str(p), "--out-dir", str(tmp_path / "o"), "--format", "json"])
    doc = json.loads(capsys.readouterr().out)
    assert doc["links"] == 1 and doc["skipped"] == 1 and rc == 1


def test_history_flags_spelling_drift_and_duplicates(tmp_path):
    h = tmp_path / "links.csv"
    h.write_text("slug,final_url,utm_source,utm_medium,utm_campaign\n"
                 "a,https://e.com?utm_source=instagram&utm_medium=social&utm_campaign=c1,instagram,social,c1\n")
    hist = load_history(str(h))
    rows = [(2, Campaign("https://e.com", source="Instagram", medium="social", campaign="c1")),
            (3, Campaign("https://e.com", source="instagram", medium="social", campaign="c1"))]
    codes = [(f.code, f.where) for f in check_history(rows, hist)]
    assert ("history_variant", "row 2") in codes and ("history_duplicate", "row 3") in codes
    assert not [c for c in codes if c == ("history_variant", "row 3")]


def test_history_needs_usable_columns(tmp_path):
    h = tmp_path / "x.csv"
    h.write_text("a,b\n1,2\n")
    with pytest.raises(ValueError):
        load_history(str(h))


def test_history_undoes_csv_injection_prefix(tmp_path):
    h = tmp_path / "links.csv"
    h.write_text("utm_source\n'=cmd\n")
    assert load_history(str(h))[0]["source"]["cmd"] == "=cmd"


def test_suggest_taxonomy_merges_spellings():
    rows = [(2, Campaign("https://e.com", source="instagram", medium="social")),
            (3, Campaign("https://e.com", source="instagram", medium="social")),
            (4, Campaign("https://e.com", source="Instagram", medium="Paid Social", campaign="x"))]
    t = suggest_taxonomy(rows)
    assert t["fields"]["source"] == {"allowed": ["instagram"]}
    assert "paid-social" in t["fields"]["medium"]["allowed"]
    parse_taxonomy(t)  # the suggestion must itself be a valid taxonomy


def test_taxonomy_init_cli_and_gen_fix(tmp_path, capsys):
    p = tmp_path / "u.txt"
    p.write_text("https://e.com/a?utm_source=ig&utm_medium=social&utm_campaign=c\n")
    out = tmp_path / "t.json"
    assert main(["taxonomy-init", str(p), "--out", str(out)]) == 0
    capsys.readouterr()
    assert main(["gen", "https://e.com", "--source", "IG", "--medium", "social", "--campaign", "c",
                 "--taxonomy", str(out), "--fix"]) == 0
    assert "utm_source=ig" in capsys.readouterr().out


def test_broken_pipe_is_quiet(monkeypatch, tmp_path):
    p = tmp_path / "u.txt"
    p.write_text("https://e.com/a?utm_source=x&utm_medium=m&utm_campaign=c\n")

    def boom(*a, **k):
        raise BrokenPipeError

    monkeypatch.setattr("builtins.print", boom)
    assert main(["audit", str(p)]) == 0


@pytest.mark.parametrize("pat", [".*.*.*x", ".*.*.*.*.*.*x", r"\w+\w+\w+", "[a-z]*[a-z]*[a-z]*"])
def test_polynomial_blowup_patterns_rejected(pat):
    assert not safe_pattern(pat)


@pytest.mark.parametrize("pat", [".*.*x", "[a-z]+[0-9]+[a-z]+", "[a-z]+-[a-z]+-[0-9]+-[a-z]+"])
def test_disjoint_or_few_repeats_allowed(pat):
    assert safe_pattern(pat)


def test_history_ragged_rows_do_not_crash(tmp_path):
    h = tmp_path / "h.csv"
    h.write_text("utm_source,utm_medium\nx,y,extra,more\nonly\n")
    assert load_history(str(h))[0]["source"]["x"] == "x"


def test_check_many_survives_worker_exception_and_limits_per_host(server):
    import threading
    live, peak, lock = [0], [0], threading.Lock()

    def fetch(u, t):
        if "boom" in u:
            raise RuntimeError("kaboom")
        with lock:
            live[0] += 1
            peak[0] = max(peak[0], live[0])
        time.sleep(0.05)
        with lock:
            live[0] -= 1
        return 200, ""

    urls = [f"http://127.0.0.1/p{i}?utm_source=a" for i in range(12)] + ["http://127.0.0.1/boom?utm_source=a"]
    res = __import__("utmkit.check", fromlist=["x"]).check_many(urls, allow_private=True, workers=8,
                                                                  per_host=2, fetch=fetch)
    assert [r.ok for r in res[:12]] == [True] * 12 and not res[12].ok and "kaboom" in res[12].problem
    assert peak[0] <= 2


def test_batch_unwritable_out_dir_is_clean_error(tmp_path, capsys):
    f = tmp_path / "afile"
    f.write_text("x")
    p = tmp_path / "s.csv"
    p.write_text("url,source,medium,campaign\nhttps://e.com,x,email,c\n")
    assert main(["batch", str(p), "--out-dir", str(f)]) == 2
    assert "cannot write output" in capsys.readouterr().err


def test_expand_makes_all_combinations(tmp_path, capsys):
    p = tmp_path / "s.csv"
    p.write_text("url,source,medium,campaign,content,name\n"
                 "https://e.com,instagram|facebook,social,c,a|b,Ad\n"
                 "https://e.com/2,x,email,c,,Plain\n")
    assert main(["batch", str(p), "--out-dir", str(tmp_path / "o"), "--expand"]) == 0
    rows = list(__import__("csv").DictReader(open(tmp_path / "o" / "links.csv")))
    assert len(rows) == 5
    assert sorted(r["slug"] for r in rows)[:4] == ["ad-facebook-a", "ad-facebook-b", "ad-instagram-a", "ad-instagram-b"]
    assert {r["utm_source"] for r in rows[:4]} == {"instagram", "facebook"}


def test_without_expand_pipe_is_literal(tmp_path):
    p = tmp_path / "s.csv"
    p.write_text("url,source,medium,campaign\nhttps://e.com,a|b,social,c\n")
    rows, _ = load_spec(str(p))
    assert rows[0][1].source == "a|b"


def test_expand_refuses_explosions():
    from utmkit.batch import expand_campaigns
    big = "|".join(str(i) for i in range(70))
    with pytest.raises(ValueError):
        expand_campaigns([(2, Campaign("https://e.com", source=big, medium=big, campaign=big, content=big))])
