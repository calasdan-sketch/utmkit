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
from typing import Any, Dict, List, Optional, Tuple

from .core import MACRO, Campaign, Finding, has_macro, sanitize

FIELDS = ("source", "medium", "campaign", "term", "content", "id",
          "source_platform", "creative_format", "marketing_tactic")
_RULE_KEYS = {"allowed", "aliases", "pattern", "max_length"}
MAX_CHECK_LEN = 200  # never run a user regex over longer values (ReDoS guard)
MAX_PATTERN_LEN = 300
try:  # Python 3.11+ moved the regex parser
    from re import _parser as _sre  # type: ignore[attr-defined]
    from re import _constants as _sre_c  # type: ignore[attr-defined]
except ImportError:  # pragma: no cover - older Pythons
    import sre_parse as _sre  # type: ignore[no-redef]
    import sre_constants as _sre_c  # type: ignore[no-redef]
_REPEATS = (_sre_c.MAX_REPEAT, _sre_c.MIN_REPEAT)
_UNBOUNDED = 8  # a repeat with a larger upper bound counts as unbounded


def _is_repeat(op) -> bool:
    return op in _REPEATS or str(op) == "POSSESSIVE_REPEAT"


def _matches(item, ch: int) -> bool:
    """Can this single regex item match character code ``ch``? (conservative: unknown -> True)"""
    op, av = item
    if op == _sre_c.LITERAL:
        return av == ch
    if op == _sre_c.IN:
        neg = any(o == _sre_c.NEGATE for o, _ in av)
        hit = False
        for o, v in av:
            if o == _sre_c.LITERAL and v == ch:
                hit = True
            elif o == _sre_c.RANGE and v[0] <= ch <= v[1]:
                hit = True
            elif o == _sre_c.CATEGORY:
                hit = True  # \d \w ... : be conservative
        return (not hit) if neg else hit
    return True


def _delimited(sub) -> bool:
    """Repeat body like ``-[a-z]+``: starts with a literal that its own repeats cannot match."""
    while len(sub) == 1 and sub[0][0] == _sre_c.SUBPATTERN:
        sub = sub[0][1][-1]
    if not sub or sub[0][0] != _sre_c.LITERAL:
        return False
    lit = sub[0][1]
    for op, av in list(sub)[1:]:
        if op in (_sre_c.BRANCH, _sre_c.SUBPATTERN):
            return False
        if _is_repeat(op) and not all(not _matches(i, lit) for i in av[2]):
            return False
    return True


def _charset(body):
    """ASCII chars a single-item repeat body can match, or None when it is more complex."""
    body = list(body)
    if len(body) != 1 or body[0][0] not in (_sre_c.LITERAL, _sre_c.IN, _sre_c.ANY):
        return None
    return {ch for ch in range(128) if _matches(body[0], ch)}


def _too_many_overlapping(items) -> bool:
    """Three+ unbounded repeats over overlapping characters with no separator: O(n^3) backtracking."""
    group: list = []  # charsets (None = unknown, treated as overlapping everything)
    for op, av in items:
        if _is_repeat(op) and av[1] > _UNBOUNDED:
            cs = _charset(av[2])
            if group and all(g is not None and cs is not None and not (g & cs) for g in group):
                group = []  # disjoint classes (e.g. [a-z]+[0-9]+) cannot trade characters
            group = [g for g in group if g is None or cs is None or (g & cs)] + [cs]
            if len(group) >= 3:
                return True
        elif op == _sre_c.LITERAL:
            group = [g for g in group if g is None or chr(av) in {chr(c) for c in g}]
        elif op not in _REPEATS and not _is_repeat(op):
            group = []
    return False


def _walk(items, in_repeat: bool) -> bool:
    """True if a variable repeat sits inside another large repeat (catastrophic backtracking)."""
    if _too_many_overlapping(items):
        return True
    for op, av in items:
        if _is_repeat(op):
            lo, hi, sub = av
            big = hi > _UNBOUNDED
            variable = lo != hi
            if in_repeat and variable:
                return True
            nested = in_repeat or big
            if big and _delimited(sub):
                nested = in_repeat  # delimiter-separated: linear, not exponential
            if _walk(sub, nested):
                return True
        elif op == _sre_c.SUBPATTERN:
            if _walk(av[-1], in_repeat):
                return True
        elif op == _sre_c.BRANCH:
            if in_repeat and _overlapping_branch(av[1]):
                return True
            if any(_walk(b, in_repeat) for b in av[1]):
                return True
        elif op in (_sre_c.ASSERT, _sre_c.ASSERT_NOT):
            if _walk(av[1], in_repeat):
                return True
    return False


def _first(items):
    for op, av in items:
        if op == _sre_c.LITERAL:
            return av
        break
    return None


def _overlapping_branch(branches) -> bool:
    """(a|ab)* style alternation: two branches that start with the same literal (or none)."""
    firsts = [_first(b) for b in branches]
    return len(set(firsts)) < len(firsts) or any(f is None for f in firsts)


def safe_pattern(pattern: str) -> bool:
    """Reject patterns that can backtrack exponentially on a short value (nested unbounded repeats)."""
    try:
        return len(pattern) <= MAX_PATTERN_LEN and not _walk(_sre.parse(pattern), False)
    except Exception:
        return False


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
                if not safe_pattern(rule["pattern"]):
                    raise ValueError(
                        f"field {name!r}: pattern is too long (>{MAX_PATTERN_LEN}) or has nested "
                        "repeats like (a+)+ that can hang the checker; simplify it")
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
    if has_macro(value):  # ad-platform placeholders are case sensitive and filled in later
        parts, last = [], 0
        for m in MACRO.finditer(value):
            parts.append(re.sub(r"\s+", "-", value[last:m.start()].lower()))
            parts.append(m.group())
            last = m.end()
        parts.append(re.sub(r"\s+", "-", value[last:].lower()))
        return "".join(parts)
    v = re.sub(r"\s+", "-", value.strip().lower())
    if rule and v in rule.aliases:
        v = rule.aliases[v]
    return v


def fix_campaign(c: Campaign, tax: Optional[Taxonomy] = None) -> Tuple[Campaign, List[str]]:
    """Return a normalised copy and a list of 'field: old -> new' changes."""
    changes: List[str] = []
    updates: Dict[str, Any] = {}
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
        if has_macro(v):  # resolved by the ad platform at click time; cannot be checked here
            continue
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


def suggest_taxonomy(campaigns, max_allowed: int = 50) -> dict:
    """Starter rules from existing links: the spellings you already use become the allowed list.

    Spellings that differ only by case/punctuation (``Instagram``/``instagram``/``insta-gram``)
    collapse to the most common one (ties: shortest, then alphabetical) and the rest become
    aliases, so ``--fix`` can repair them. Review the result before enforcing it.
    """
    from collections import Counter
    from .core import _canon

    fields: dict = {}
    for f in ("source", "medium"):
        counts: Counter = Counter()
        for _, c in campaigns:
            v = normalize_value(getattr(c, f))
            if v:
                counts[v] += 1
        groups: dict = {}
        for v, n in counts.items():
            groups.setdefault(_canon(v), []).append((-n, len(v), v))
        allowed, aliases = [], {}
        for forms in groups.values():
            forms.sort()
            best = forms[0][2]
            allowed.append(best)
            aliases.update({v: best for _, _, v in forms[1:]})
        if 0 < len(allowed) <= max_allowed:
            rule: dict = {"allowed": sorted(allowed)}
            if aliases:
                rule["aliases"] = dict(sorted(aliases.items()))
            fields[f] = rule
    longest = max((len(c.campaign) for _, c in campaigns), default=0)
    if longest:
        fields["campaign"] = {"max_length": max(40, longest)}
    return {"fields": fields, "required": ["source", "medium", "campaign"]}
