"""URL building, slug and validation tests."""
import pytest

from utmkit.core import Campaign, build_url, slugify, unique_slug, validate_campaign


def test_build_url_appends_utm():
    url = build_url(Campaign("https://ex.com/landing", source="instagram", medium="social",
                             campaign="launch26"))
    assert url == "https://ex.com/landing?utm_source=instagram&utm_medium=social&utm_campaign=launch26"


def test_build_url_preserves_existing_query():
    url = build_url(Campaign("https://ex.com/p?id=7&ref=nav", source="email", campaign="wk42"))
    assert "id=7" in url and "ref=nav" in url and "utm_source=email" in url


def test_build_url_overrides_existing_utm():
    url = build_url(Campaign("https://ex.com/?utm_source=old", source="new"))
    assert "utm_source=new" in url and "old" not in url


def test_build_url_encodes_spaces_and_fragment_kept():
    url = build_url(Campaign("https://ex.com/a#top", source="a b", campaign="c"))
    assert "utm_source=a+b" in url or "utm_source=a%20b" in url
    assert url.endswith("#top")


def test_build_url_empty_rejected():
    with pytest.raises(ValueError):
        build_url(Campaign(""))


def test_slugify():
    assert slugify("Spring Sale — 20% OFF!") == "spring-sale-20-off"
    assert slugify("Ünïcode Ünicorn") == "unicode-unicorn"
    assert slugify("***") == "link"
    assert slugify("") == "link"


def test_unique_slug_suffixes():
    taken = []
    assert unique_slug("a", taken) == "a" or (taken.append("a") or True)
    taken.clear()
    first = unique_slug("a", taken)
    taken.append(first)
    second = unique_slug("a", taken)
    taken.append(second)
    third = unique_slug("a", taken)
    assert (first, second, third) == ("a", "a-2", "a-3")


def test_validate_required_source():
    findings = validate_campaign(Campaign("https://x.com"))
    assert any(f.code == "no_source" and f.severity == "error" for f in findings)


def test_validate_case_and_spaces_warn():
    findings = validate_campaign(Campaign("https://x.com", source="Instagram", medium="email",
                                          campaign="Spring Sale"))
    codes = [f.code for f in findings]
    assert "not_lowercase" in codes and "has_spaces" in codes


def test_validate_unusual_medium_and_scheme():
    findings = validate_campaign(Campaign("ex.com", source="a", medium="teleport"))
    codes = [f.code for f in findings]
    assert "unusual_medium" in codes and "no_scheme" in codes


def test_validate_known_mediums_quiet():
    for medium in ("email", "social", "cpc", "qr", "print"):
        assert validate_campaign(Campaign("https://x.com", source="a", medium=medium)) == []


def test_non_standard_utm_params_survive():
    url = build_url(Campaign("https://ex.com/?utm_id=42&utm_source=old", source="new"))
    assert "utm_id=42" in url and "utm_source=new" in url and "old" not in url
