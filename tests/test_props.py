"""Property-based tests (need `pip install hypothesis`; skipped otherwise)."""
import re

import pytest

from utmkit import Campaign, build_url
from utmkit.core import existing_utm, has_macro, sanitize, slugify, strip_macros, validate_campaign

pytest.importorskip("hypothesis")
from hypothesis import given, settings, strategies as st  # noqa: E402

_text = st.text(alphabet=st.characters(blacklist_categories=("Cs",)), max_size=30)
_query = st.lists(st.sampled_from(["flag", "a=b%2Cc", "sig=a+b%3D%3D", "x=1;y=2", "p=%7Efoo/bar", "e=", "k=v"]),
                  max_size=4).map("&".join)


@settings(max_examples=300, deadline=None)
@given(q=_query, src=_text, med=_text, camp=_text, term=_text)
def test_prop_roundtrip_and_foreign_query_untouched(q, src, med, camp, term):
    c = Campaign("https://example.com/p" + ("?" + q if q else ""), source=src, medium=med,
                 campaign=camp, term=term)
    try:
        url = build_url(c)
    except ValueError:
        return
    if q:
        assert url.split("?", 1)[1].startswith(q + "&") or not c.utm()
    got = existing_utm(url)
    for k, v in c.utm().items():
        if not has_macro(v):
            assert got[k] == v


@settings(max_examples=200, deadline=None)
@given(src=_text, camp=_text)
def test_prop_build_is_idempotent(src, camp):
    c = Campaign("https://example.com/?z=1", source=src, campaign=camp)
    try:
        once = build_url(c)
    except ValueError:
        return
    again = build_url(Campaign(once, source=src, campaign=camp))
    assert again == once


@settings(max_examples=300, deadline=None)
@given(text=st.text(max_size=300))
def test_prop_slug_is_filesystem_safe(text):
    s = slugify(text)
    assert 0 < len(s) <= 80 and re.fullmatch(r"[a-z0-9-]+", s)
    assert s.split("-")[0] not in {"con", "nul", "aux", "prn"} or "-" in s


@settings(max_examples=300, deadline=None)
@given(text=st.text(max_size=100))
def test_prop_sanitize_removes_everything_dangerous(text):
    from utmkit.core import has_unsafe
    assert not has_unsafe(sanitize(text))


@settings(max_examples=200, deadline=None)
@given(text=st.text(max_size=80))
def test_prop_strip_macros_has_no_macro(text):
    assert not has_macro(strip_macros(text)) or MACRO_NESTED.search(text)


MACRO_NESTED = re.compile(r"\{\{\{|\}\}\}|\{\{[^}]*\{")  # nesting can re-form a macro after stripping


@settings(max_examples=150, deadline=None)
@given(text=st.text(max_size=60))
def test_prop_validate_never_raises(text):
    validate_campaign(Campaign("https://example.com/" + text, source=text, medium=text, campaign=text), ga4=True)
