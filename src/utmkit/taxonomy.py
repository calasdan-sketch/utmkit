"""Naming-convention enforcement: a JSON taxonomy file checked (and optionally fixed) per row.

Example::

    {
      "fields": {
        "source":   {"allowed": ["instagram", "newsletter"], "aliases": {"ig": "instagram"}},
        "medium":   {"allowed": ["social", "email", "cpc"]},
        "campaign": {"pattern": "[a-z0-9]+-[0-9]{2}"}
      },
      "required": ["source", "medium", "campaign"]
    }

Bad files fail closed (ValueError) rather than silently checking nothing.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field, replace
from typing import Dict, List, Optional, Tuple

from .core import Campaign, Finding, sanitize

FIELDS = ("source", "medium", "campaign", "term", "content", "id",
          "source_platform", "creative_format", "marketing_tactic")
_RULE_KEYS = {"allowed", "aliases", "pattern", "max_length"}
MAX_CHECK_LEN = 500  # never run a user regex over longer values (ReDoS guard)


@dataclass
class FieldRule:
    allowed: Optional[List[str]] = None
    aliases: Dict[str, str] = field(default_factory=dict)
    pattern: Optional["re.Pattern[str]"] = None
    max_length: Optional[int] = None


@dataclass
class Taxonomy:
    fields: Dict[str, FieldRule] = field(default_factory=dict)
    required: List[str] = field(default_factory=list)


def parse_taxonomy(data: object) -> Taxonomy:
    if not isinstance(data, dict) or set(data) - {"fields", "required"}:
        raise ValueError("taxonomy must be an object with only 'fields' and 'required'")
    tax = Taxonomy()
    req = data.get("required", [])
    if not isinstance(req, list) or any(r not in FIELDS for r in req):
        raise ValueError(f"'required' must be a list of: {', '.join(FIELDS)}")
    tax.required = list(req)
    fields = data.get("fields", {})
    if not isinstance(fields, dict):
        raise ValueError("'fields' must be an object")
    for name, rule in fields.items():
        if name not in FIELDS:
            raise ValueError(f"unknown taxonomy field {name!r}")
        if not isinstance(rule, dict) or set(rule) - _RULE_KEYS:
            raise ValueError(f"field {name!r}: rule keys must be among {sorted(_RULE_KEYS)}")
        fr = FieldRule()
        if "allowed" in rule:
            if not isinstance(rule["allowed"], list) or not all(isinstance(x, str) for x in rule["allowed"]):
                raise ValueError(f"field {name!r}: 'allowed' must be a list of strings")
            fr.allowed = rule["allowed"]
        if "aliases" in rule:
            al = rule["aliases"]
            if not isinstance(al, dict) or not all(
                    isinstance(k, str) and isinstance(v, str) for k, v in al.items()):
                raise ValueError(f"field {name!r}: 'aliases' must map strings to strings")
            fr.aliases = {k.lower(): v for k, v in al.items()}
        if "pattern" in rule:
            try:
                fr.pattern = re.compile(rule["pattern"])
            except (re.error, TypeError) as e:
                raise ValueError(f"field {name!r}: bad pattern: {e}") from None
        if "max_length" in rule:
            if not isinstance(rule["max_length"], int) or rule["max_length"] < 1:
                raise ValueError(f"field {name!r}: 'max_length' must be a positive integer")
            fr.max_length = rule["max_length"]
        tax.fields[name] = fr
    return tax


def load_taxonomy(path: str) -> Taxonomy:
    try:
        with open(path, encoding="utf-8-sig") as fh:
            return parse_taxonomy(json.load(fh))
    except json.JSONDecodeError as e:
        raise ValueError(f"taxonomy {path}: invalid JSON ({e})") from None


def normalize_value(value: str, rule: Optional[FieldRule] = None) -> str:
    """lowercase, whitespace runs -> '-', then apply the field's aliases."""
    v = re.sub(r"\s+", "-", value.strip().lower())
    if rule and v in rule.aliases:
        v = rule.aliases[v]
    return v


def fix_campaign(c: Campaign, tax: Optional[Taxonomy] = None) -> Tuple[Campaign, List[str]]:
    """Return a normalised copy and a list of 'field: old -> new' changes."""
    changes: List[str] = []
    updates = {}
    for f in FIELDS:
        old = getattr(c, f)
        if not old:
            continue
        new = normalize_value(old, tax.fields.get(f) if tax else None)
        if new != old:
            updates[f] = new
            changes.append(f"{f}: {sanitize(old)!r} -> {sanitize(new)!r}")
    return (replace(c, **updates) if updates else c), changes


def check_taxonomy(c: Campaign, tax: Taxonomy, where: str) -> List[Finding]:
    out: List[Finding] = []
    for f in tax.required:
        if not getattr(c, f):
            out.append(Finding("error", "taxonomy_required", where, f"{f} is required by the taxonomy"))
    for f, rule in tax.fields.items():
        v = getattr(c, f)
        if not v:
            continue
        if rule.max_length and len(v) > rule.max_length:
            out.append(Finding("error", "taxonomy_too_long", where,
                               f"{f} is {len(v)} chars; max {rule.max_length}"))
        if rule.allowed is not None and v not in rule.allowed:
            hint = ""
            alias = rule.aliases.get(v.lower())
            if alias:
                hint = f" (did you mean {alias!r}?)"
            out.append(Finding("error", "taxonomy_not_allowed", where,
                               f"{f}={sanitize(v)!r} is not in the allowed list{hint}"))
        if rule.pattern is not None:
            if len(v) > MAX_CHECK_LEN or not rule.pattern.fullmatch(v):
                out.append(Finding("error", "taxonomy_pattern", where,
                                   f"{f}={sanitize(v[:80])!r} does not match /{rule.pattern.pattern}/"))
    return out
