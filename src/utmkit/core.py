"""UTM link building, deterministic slugs and campaign validation."""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Dict, List, Optional
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

UTM_KEYS = ("utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content")
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
    extra: Dict[str, str] = field(default_factory=dict)

    def utm(self) -> Dict[str, str]:
        pairs = {
            "utm_source": self.source,
            "utm_medium": self.medium,
            "utm_campaign": self.campaign,
            "utm_term": self.term,
            "utm_content": self.content,
        }
        return {k: v for k, v in pairs.items() if v}


@dataclass(frozen=True)
class Finding:
    severity: str  # error | warn
    code: str
    where: str
    detail: str


def build_url(campaign: Campaign) -> str:
    """Merge UTM parameters into the URL, preserving existing query params.

    Existing utm_* keys are overridden by the campaign values (the campaign is
    the source of truth); other existing params survive untouched.
    """
    if not campaign.url:
        raise ValueError("campaign url is empty")
    parts = urlsplit(campaign.url)
    kept = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
            if not k.lower().startswith("utm_")]
    merged = kept + list(campaign.utm().items()) + list(campaign.extra.items())
    return urlunsplit((parts.scheme, parts.netloc, parts.path,
                       urlencode(merged), parts.fragment))


def slugify(text: str, fallback: str = "link") -> str:
    """URL-safe, lowercase, deterministic slug."""
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    slug = _SLUG_CLEAN.sub("-", text.lower()).strip("-")
    return slug or fallback


def unique_slug(base: str, taken: List[str]) -> str:
    """first-wins with -2, -3 ... suffixes for collisions."""
    if base not in taken:
        return base
    n = 2
    while f"{base}-{n}" in taken:
        n += 1
    return f"{base}-{n}"


def validate_campaign(c: Campaign, where: str = "") -> List[Finding]:
    """Flag the mistakes that silently wreck campaign data."""
    out: List[Finding] = []
    where = where or c.name or c.url
    if not c.url:
        out.append(Finding("error", "no_url", where, "row has no url"))
        return out
    if not c.source:
        out.append(Finding("error", "no_source", where, "utm_source is required"))
    for key, value in (("utm_source", c.source), ("utm_medium", c.medium),
                       ("utm_campaign", c.campaign), ("utm_term", c.term),
                       ("utm_content", c.content)):
        if value and value != value.lower():
            out.append(Finding("warn", "not_lowercase", where,
                               f"{key}={value!r} should be lowercase (analytics tools split cases)"))
        if " " in value:
            out.append(Finding("warn", "has_spaces", where,
                               f"{key}={value!r} has spaces; prefer dashes"))
    if c.medium and c.medium not in ("email", "social", "cpc", "ppc", "affiliate",
                                     "organic", "referral", "display", "qr", "print"):
        out.append(Finding("warn", "unusual_medium", where,
                           f"utm_medium={c.medium!r} is not a common value "
                           "(email/social/cpc/...): fine if intentional"))
    if c.url and not c.url.lower().startswith(("http://", "https://")):
        out.append(Finding("warn", "no_scheme", where, f"url {c.url!r} has no http(s) scheme"))
    return out
