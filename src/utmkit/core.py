"""UTM link building, deterministic slugs and campaign validation."""
from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Dict, List, Optional
from urllib.parse import quote, unquote, urlsplit, urlunsplit

UTM_KEYS = ("utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
            "utm_id", "utm_source_platform", "utm_creative_format", "utm_marketing_tactic")
MAX_SLUG = 80
_RESERVED = {"con", "prn", "aux", "nul", *(f"com{i}" for i in range(1, 10)),
             *(f"lpt{i}" for i in range(1, 10))}
# control chars, bidi controls/isolates, zero-width and BOM
_UNSAFE = re.compile("[\x00-\x1f\x7f-\x9f\u200b-\u200f\u202a-\u202e\u2060-\u2069\ufeff]")


def sanitize(text: str) -> str:
    """Make untrusted text safe to print: control/bidi/zero-width chars become \\uXXXX."""
    return _UNSAFE.sub(lambda m: "\\u%04x" % ord(m.group()), text)


def has_unsafe(text: str) -> bool:
    return bool(_UNSAFE.search(text))
_SLUG_CLEAN = re.compile(r"[^a-z0-9]+")


@dataclass
class Campaign:
    url: str
    source: str = ""
    medium: str = ""
    campaign: str = ""
    term: str = ""
    content: str = ""
    name: str = ""
    id: str = ""
    source_platform: str = ""
    creative_format: str = ""
    marketing_tactic: str = ""
    extra: Dict[str, str] = field(default_factory=dict)

    def utm(self) -> Dict[str, str]:
        pairs = {
            "utm_source": self.source,
            "utm_medium": self.medium,
            "utm_campaign": self.campaign,
            "utm_term": self.term,
            "utm_content": self.content,
            "utm_id": self.id,
            "utm_source_platform": self.source_platform,
            "utm_creative_format": self.creative_format,
            "utm_marketing_tactic": self.marketing_tactic,
        }
        return {k: v for k, v in pairs.items() if v}


@dataclass(frozen=True)
class Finding:
    severity: str  # error | warn
    code: str
    where: str
    detail: str


def _key(pair: str) -> str:
    return unquote(pair.split("=", 1)[0].replace("+", " ")).lower()


def build_url(campaign: Campaign) -> str:
    """Merge UTM parameters into the URL without touching anything else.

    The existing query string is kept byte-for-byte (valueless flags, ``;``,
    ``+``, percent-escapes, signed tokens); only the nine managed utm_* keys
    are removed and replaced by the campaign's values (the campaign is the
    source of truth). Other ``utm_*`` keys (custom ones) survive.
    """
    if not campaign.url:
        raise ValueError("campaign url is empty")
    parts = urlsplit(campaign.url)
    kept = [p for p in parts.query.split("&") if p and _key(p) not in UTM_KEYS]
    new = [f"{k}={quote(v, safe='')}" for k, v in
           list(campaign.utm().items()) + list(campaign.extra.items())]
    return urlunsplit((parts.scheme, parts.netloc, parts.path,
                       "&".join(kept + new), parts.fragment))


def existing_utm(url: str) -> Dict[str, str]:
    """Managed utm_* keys already present in a URL (decoded)."""
    out: Dict[str, str] = {}
    for p in urlsplit(url).query.split("&"):
        k = _key(p)
        if k in UTM_KEYS:
            out[k] = unquote(p.split("=", 1)[1].replace("+", " ")) if "=" in p else ""
    return out


def campaign_from_url(url: str, name: str = "") -> Campaign:
    """Read the managed utm_* values already inside a URL back into a Campaign (for auditing).

    ``url`` keeps the whole original URL; a later ``build_url`` replaces the same keys with
    the same values, so the result is the identical link.
    """
    old = existing_utm(url)
    return Campaign(url=url, name=name, **{attr: old.get(key, "") for key, attr in _VALUES})


def slugify(text: str, fallback: str = "link") -> str:
    """URL/filename-safe, lowercase, deterministic slug (<= 80 chars).

    Names with no ASCII letters (e.g. Greek) get ``link-<hash>`` so different
    names stay different; over-long input is truncated with a hash suffix;
    Windows reserved device names (con, nul, com1...) get a ``-link`` suffix.
    """
    ascii_text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    slug = _SLUG_CLEAN.sub("-", ascii_text.lower()).strip("-")
    digest = hashlib.sha1(text.encode("utf-8", "surrogatepass")).hexdigest()[:8]
    if not slug:
        return f"{fallback}-{digest}" if any(ch.isalnum() for ch in text) else fallback
    if len(slug) > MAX_SLUG:
        slug = slug[:MAX_SLUG - 9].rstrip("-") + "-" + digest
    if slug.split("-")[0] in _RESERVED and "-" not in slug:
        slug += "-link"
    return slug


def unique_slug(base: str, taken) -> str:
    """first-wins with -2, -3 ... suffixes for collisions."""
    if base not in taken:
        return base
    n = 2
    while f"{base}-{n}" in taken:
        n += 1
    return f"{base}-{n}"


_VALUES = (("utm_source", "source"), ("utm_medium", "medium"), ("utm_campaign", "campaign"),
           ("utm_term", "term"), ("utm_content", "content"), ("utm_id", "id"),
           ("utm_source_platform", "source_platform"),
           ("utm_creative_format", "creative_format"),
           ("utm_marketing_tactic", "marketing_tactic"))
MAX_URL = 2000  # conservative cross-browser/ad-platform length (unverified per platform)
_EMAIL = re.compile(r"[^@\s/=&]{1,64}@[^@\s/=&]{1,255}\.[A-Za-z]{2,}")
_DANGEROUS = {"javascript", "data", "vbscript", "file", "blob", "about"}


def validate_campaign(c: Campaign, where: str = "", ga4: bool = False,
                      built: Optional[str] = None) -> List[Finding]:
    """Flag the mistakes that silently wreck campaign data.

    ``ga4=True`` adds the GA4-specific checks (missing medium/campaign, channel
    prediction) and replaces the generic ``unusual_medium`` hint.
    """
    from .channels import ga4_channel

    out: List[Finding] = []
    where = sanitize(where or c.name or c.url)
    if not c.url:
        out.append(Finding("error", "no_url", where, "row has no url"))
        return out
    try:
        scheme = urlsplit(c.url).scheme.lower()
    except ValueError:  # e.g. "http://[::1" - urlsplit refuses it
        out.append(Finding("error", "bad_host", where, "url is malformed (bad host brackets); row skipped"))
        return out
    if scheme and scheme not in ("http", "https") and ("://" in c.url or scheme in _DANGEROUS):
        out.append(Finding("error", "bad_scheme", where,
                           f"url scheme {sanitize(scheme)!r} is not http/https; row skipped"))
        return out
    try:
        sp = urlsplit(c.url)
        sp.port  # noqa: B018 - raises ValueError for a non-numeric / out-of-range port
        host_ok = bool(sp.hostname)
    except ValueError:
        host_ok = False
    if scheme in ("http", "https") and not host_ok:
        out.append(Finding("error", "bad_host", where,
                           "url has no host or an invalid port; row skipped"))
        return out
    if has_unsafe(c.url) or " " in c.url.strip():
        out.append(Finding("error", "bad_url_chars", where,
                           "url contains spaces or control/invisible characters"))
    if not scheme or scheme not in ("http", "https"):
        out.append(Finding("warn", "no_scheme", where,
                           f"url {sanitize(c.url)!r} has no http(s) scheme"))
    if not c.source:
        out.append(Finding("error", "no_source", where, "utm_source is required"))
    if ga4 and not c.medium:
        out.append(Finding("warn", "no_medium", where,
                           "utm_medium missing: GA4 reports it as (not set) "
                           "(Google: always use source, medium and campaign)"))
    if ga4 and not c.campaign:
        out.append(Finding("warn", "no_campaign", where,
                           "utm_campaign missing: GA4 reports it as (not set)"))
    for key, attr in _VALUES:
        value = getattr(c, attr)
        if not value:
            continue
        if has_unsafe(value):
            out.append(Finding("error", "bad_value_chars", where,
                               f"{key}={sanitize(value)!r} has control/invisible characters"))
            continue
        if value != value.lower():
            out.append(Finding("warn", "not_lowercase", where,
                               f"{key}={value!r} should be lowercase (GA4 values are case sensitive)"))
        if " " in value:
            out.append(Finding("warn", "has_spaces", where,
                               f"{key}={value!r} has spaces; prefer dashes"))
        if _EMAIL.search(unquote(value)):
            out.append(Finding("warn", "pii_email", where,
                               f"{key} looks like an email address; analytics terms forbid "
                               "personal data in URLs and it ends up in reports and logs"))
        if re.search(r"%[0-9a-fA-F]{2}", value):
            out.append(Finding("warn", "pre_encoded", where,
                               f"{key}={value!r} looks already percent-encoded; it would be encoded twice"))
    if not ga4 and c.medium and c.medium not in (
            "email", "social", "cpc", "ppc", "affiliate", "organic", "referral",
            "display", "qr", "print"):
        out.append(Finding("warn", "unusual_medium", where,
                           f"utm_medium={sanitize(c.medium)!r} is not a common value "
                           "(email/social/cpc/...): fine if intentional"))
    if ga4 and c.medium and c.source:
        ch = ga4_channel(c.source, c.medium, c.campaign)
        if ch.name == "Unassigned":
            out.append(Finding("warn", "ga4_unassigned", where,
                               f"source={c.source!r} medium={c.medium!r} matches no GA4 default "
                               "channel rule, so sessions land in 'Unassigned' "
                               "(use e.g. email, social, cpc, display, affiliate, referral)"))
    old = existing_utm(c.url)
    new = c.utm()
    for k, v in old.items():
        if k in new and new[k] != v:
            out.append(Finding("warn", "overrides_existing", where,
                               f"url already has {k}={sanitize(v)!r}; replaced by {sanitize(new[k])!r}"))
    try:
        if len(built if built is not None else build_url(c)) > MAX_URL:
            out.append(Finding("warn", "url_too_long", where,
                               f"final URL exceeds {MAX_URL} characters; some platforms truncate"))
    except ValueError:
        pass
    return out


def _canon(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.lower())


def validate_rows(rows) -> List[Finding]:
    """Cross-row checks over [(row_no, Campaign)]: the inconsistencies a single-row check can't see.

    - case_variants: ``Instagram`` vs ``instagram`` in the same column (GA4 splits them)
    - near_duplicate: ``paid-social`` vs ``paid_social`` vs ``paidsocial``
    - duplicate_link: two rows that build the identical final URL
    """
    out: List[Finding] = []
    seen_links: Dict[str, int] = {}
    variants: Dict[str, Dict[str, Dict[str, int]]] = {}
    for row_no, c in rows:
        if c.url:
            try:
                u = build_url(c)
            except ValueError:
                u = ""
            if u:
                if u in seen_links:
                    out.append(Finding("warn", "duplicate_link", f"row {row_no}",
                                       f"same final URL as row {seen_links[u]}"))
                else:
                    seen_links[u] = row_no
        for _, attr in _VALUES:
            v = getattr(c, attr)
            if v:
                variants.setdefault(attr, {}).setdefault(_canon(v), {}).setdefault(v, row_no)
    for attr, groups in variants.items():
        for forms in groups.values():
            if len(forms) < 2:
                continue
            lowers = {f.lower() for f in forms}
            code = "case_variants" if len(lowers) == 1 else "near_duplicate"
            listing = ", ".join(f"{sanitize(f)!r} (row {r})" for f, r in forms.items())
            out.append(Finding("warn", code, "all rows",
                               f"utm {attr} written {len(forms)} ways: {listing}"))
    return out
