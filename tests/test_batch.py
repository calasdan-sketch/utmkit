"""Batch, QR-backend and CLI tests."""
import csv
import os

from utmkit.batch import load_campaigns, run_batch, write_csv
from utmkit.cli import main


def write_spec(tmp, rows):
    p = tmp / "spec.csv"
    with open(p, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["url", "source", "medium", "campaign", "name"])
        for r in rows:
            w.writerow(r)
    return str(p)


def test_load_and_batch(tmp_path):
    spec = write_spec(tmp_path, [
        ["https://ex.com/a", "instagram", "social", "launch", "Spring Ad"],
        ["https://ex.com/b", "newsletter", "email", "launch", "Spring Ad"],
    ])
    campaigns = load_campaigns(spec)
    assert len(campaigns) == 2 and campaigns[0][1].source == "instagram"
    result = run_batch(campaigns, str(tmp_path / "out"))
    assert len(result.rows) == 2
    # identical names get unique slugs
    slugs = [r["slug"] for r in result.rows]
    assert slugs == ["spring-ad", "spring-ad-2"]
    assert result.rows[0]["final_url"].startswith("https://ex.com/a?utm_source=instagram")


def test_qr_with_fake_backend(tmp_path):
    calls = []

    def fake_backend(data, path):
        calls.append((data, path))
        with open(path, "wb") as fh:
            fh.write(b"\x89PNG")

    spec = write_spec(tmp_path, [["https://ex.com", "ig", "social", "c", "n"]])
    result = run_batch(load_campaigns(spec), str(tmp_path / "out"), qr=True, qr_backend=fake_backend)
    assert len(calls) == 1 and result.rows[0]["qr"] == "n.png"
    assert os.path.exists(os.path.join(str(tmp_path / "out"), "n.png"))


def test_qr_unavailable_warns_not_crashes(tmp_path):
    spec = write_spec(tmp_path, [["https://ex.com", "ig", "social", "c", "n"]])
    result = run_batch(load_campaigns(spec), str(tmp_path / "out"), qr=True, qr_backend=None)
    assert any(f.code == "qr_unavailable" for f in result.findings) or result.qr_written


def test_html_index(tmp_path):
    spec = write_spec(tmp_path, [["https://ex.com", "ig", "social", "c", "Home"]])
    run_batch(load_campaigns(spec), str(tmp_path / "out"), html_index=True)
    html = (tmp_path / "out" / "index.html").read_text(encoding="utf-8")
    assert "utm_source=ig" in html and "<table" in html


def test_write_csv(tmp_path):
    spec = write_spec(tmp_path, [["https://ex.com", "ig", "social", "c", "x"]])
    result = run_batch(load_campaigns(spec), str(tmp_path / "out"))
    out = tmp_path / "out" / "links.csv"
    write_csv(result, str(out))
    rows = list(csv.DictReader(open(out, encoding="utf-8")))
    assert rows[0]["slug"] == "x" and rows[0]["final_url"].startswith("https://ex.com?")


def test_cli_gen(capsys):
    assert main(["gen", "https://ex.com", "--source", "ig", "--medium", "social",
                 "--campaign", "launch"]) == 0
    assert "utm_source=ig" in capsys.readouterr().out


def test_cli_gen_requires_source(capsys):
    assert main(["gen", "https://ex.com"]) == 1


def test_cli_batch_and_validate(tmp_path, capsys):
    spec = write_spec(tmp_path, [
        ["https://ex.com/a", "ig", "social", "launch", "One"],
        ["https://ex.com/b", "Newsletter", "email", "launch", "Two"],
    ])
    assert main(["batch", spec, "--out-dir", str(tmp_path / "o"), "--html"]) == 0
    assert (tmp_path / "o" / "links.csv").exists() and (tmp_path / "o" / "index.html").exists()
    capsys.readouterr()
    assert main(["validate", spec]) == 0  # warnings only
    assert main(["validate", spec, "--strict"]) == 1


def test_cli_bad_spec(tmp_path):
    bad = tmp_path / "bad.csv"
    bad.write_text("nope,columns\n1,2\n", encoding="utf-8")  # lacks the url column
    assert main(["batch", str(bad)]) == 2


def test_batch_skips_error_rows_instead_of_crashing(tmp_path):
    spec = write_spec(tmp_path, [
        ["", "instagram", "social", "launch", "No URL"],
        ["https://ex.com/a", "instagram", "social", "launch", "Good"],
    ])
    out = tmp_path / "out"
    assert main(["batch", spec, "--out-dir", str(out)]) == 1
    rows = list(csv.DictReader(open(out / "links.csv", encoding="utf-8")))
    assert [r["slug"] for r in rows] == ["good"]


def test_html_index_never_links_non_http_urls(tmp_path):
    spec = write_spec(tmp_path, [["javascript:alert(1)", "x", "email", "c", "bad"]])
    out = tmp_path / "out"
    main(["batch", spec, "--out-dir", str(out), "--html"])
    page = (out / "index.html").read_text(encoding="utf-8")
    assert "href='javascript" not in page and "javascript:alert(1)" in page


def test_fix_flag_on_gen_and_batch(tmp_path, capsys):
    assert main(["gen", "https://ex.com", "--source", " Instagram Ads ", "--fix"]) == 0
    out, err = capsys.readouterr()
    assert "utm_source=instagram-ads" in out and "INFO" in err and "fixed" in err
    assert main(["gen", "https://ex.com", "--source", " Instagram Ads "]) == 0
    out, err = capsys.readouterr()
    assert "Instagram+Ads" in out and "not_lowercase" in err     # unchanged without --fix
    spec = write_spec(tmp_path, [["https://ex.com/a", "Instagram Ads", "Social", "launch", "One"]])
    assert main(["batch", spec, "--out-dir", str(tmp_path / "o"), "--fix", "--strict"]) == 0
    rows = list(csv.DictReader(open(tmp_path / "o" / "links.csv", encoding="utf-8")))
    assert "utm_source=instagram-ads&utm_medium=social" in rows[0]["final_url"]


def test_duplicate_final_url_warns(tmp_path, capsys):
    row = ["https://ex.com/a", "ig", "social", "launch", "One"]
    spec = write_spec(tmp_path, [row, ["https://ex.com/b", "ig", "social", "launch", "Two"], row])
    result = run_batch(load_campaigns(spec), str(tmp_path / "o"))
    dups = [f for f in result.findings if f.code == "duplicate_url"]
    assert len(dups) == 1 and dups[0].severity == "warn"
    assert "row 2" in dups[0].detail and dups[0].where == "row 4"
    assert main(["batch", spec, "--out-dir", str(tmp_path / "o")]) == 0
    assert main(["batch", spec, "--out-dir", str(tmp_path / "o"), "--strict"]) == 1


RULES = {"source": ["instagram", "facebook"], "medium": ["social", "email", "cpc", "qr"],
         "campaign_pattern": "^[a-z0-9-]+$"}


def test_rules_file_allow_list(tmp_path, capsys):
    import json
    rules = tmp_path / "rules.json"
    rules.write_text(json.dumps(RULES), encoding="utf-8")
    spec = write_spec(tmp_path, [["https://ex.com/a", "instagram", "Social-Media", "launch", "One"]])
    assert main(["validate", spec, "--rules", str(rules)]) == 1
    assert "not_allowed" in capsys.readouterr().out
    assert main(["batch", spec, "--out-dir", str(tmp_path / "o"), "--rules", str(rules)]) == 1
    assert main(["gen", "https://ex.com", "--source", "instagram", "--medium", "social",
                 "--campaign", "Spring Sale", "--rules", str(rules)]) == 1     # campaign pattern
    assert main(["gen", "https://ex.com", "--source", "facebook", "--medium", "cpc",
                 "--campaign", "spring-sale", "--rules", str(rules)]) == 0
    rules.write_text("{not json", encoding="utf-8")
    assert main(["validate", spec, "--rules", str(rules)]) == 2
    rules.write_text('{"medium": "social"}', encoding="utf-8")                  # must be a list
    assert main(["validate", spec, "--rules", str(rules)]) == 2
    rules.write_text('{"campaign_pattern": "("}', encoding="utf-8")             # bad regex
    assert main(["validate", spec, "--rules", str(rules)]) == 2
    assert main(["validate", spec, "--rules", str(tmp_path / "missing.json")]) == 2


def test_parse_existing_url(capsys):
    import json
    url = "https://x.com/?utm_source=IG&utm_medium=social"
    assert main(["parse", url]) == 0
    out = capsys.readouterr().out
    assert "utm_source: IG" in out and "not_lowercase" in out and "no_campaign" in out
    assert main(["parse", url, "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["url"] == "https://x.com/" and data["utm"]["utm_source"] == "IG"
    codes = {(f["severity"], f["code"]) for f in data["findings"]}
    assert ("warn", "not_lowercase") in codes and ("warn", "no_campaign") in codes
    assert main(["parse", "https://x.com/?id=7"]) == 1                    # no utm_source: error
