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
