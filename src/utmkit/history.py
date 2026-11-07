"""Compare a new batch with links you already made (an earlier ``links.csv`` or spec).

The usual drift is across batches, not inside one: last quarter's ``instagram`` becomes this
quarter's ``Instagram`` or ``ig``. GA4 then reports them as different sources forever.
"""
from __future__ import annotations

import csv
from typing import Dict, List, Tuple

from .core import Campaign, Finding, _VALUES, _canon, build_url, campaign_from_url, sanitize

MAX_HISTORY = 200_000
_OUT_COLS = {"utm_source": "source", "utm_medium": "medium", "utm_campaign": "campaign"}


def load_history(path: str) -> Tuple[Dict[str, Dict[str, str]], Dict[str, int]]:
    """Return ({attr: {canon: first-seen spelling}}, {final_url: row}) from a CSV.

    Reads ``utm_*`` columns (as written by ``batch``) and/or a ``final_url`` / ``url`` column
    whose query holds the tags. Raises ValueError when the file has neither.
    """
    values: Dict[str, Dict[str, str]] = {}
    links: Dict[str, int] = {}
    try:
        with open(path, newline="", encoding="utf-8-sig") as fh:
            reader = csv.DictReader(fh)
            cols = [c.strip().lower() for c in (reader.fieldnames or [])]
            if not ({"final_url", "url"} & set(cols) or any(c in cols for c in _OUT_COLS)):
                raise ValueError("history CSV needs utm_source/utm_medium/... columns or a final_url column")
            for i, raw in enumerate(reader, start=2):
                if i > MAX_HISTORY:
                    raise ValueError(f"history CSV has more than {MAX_HISTORY} rows")
                row = {k.strip().lower(): (v or "").strip() for k, v in raw.items()
                       if isinstance(k, str) and not isinstance(v, list)}
                url = row.get("final_url") or row.get("url") or ""
                if url:
                    links.setdefault(url, i)
                found = campaign_from_url(url) if url else Campaign(url="")
                for key, attr in _VALUES:
                    v = row.get(key) or getattr(found, attr)
                    if v.startswith("'") and v[1:2] in ("=", "+", "-", "@"):
                        v = v[1:]  # undo our own CSV-injection prefix
                    if v:
                        values.setdefault(attr, {}).setdefault(_canon(v), v)
    except UnicodeDecodeError:
        raise ValueError("history CSV is not valid UTF-8") from None
    except csv.Error as e:
        raise ValueError(f"history CSV is malformed: {e}") from None
    return values, links


def check_history(rows, history) -> List[Finding]:
    """Findings for [(row_no, Campaign)] against :func:`load_history` output."""
    values, links = history
    out: List[Finding] = []
    for row_no, c in rows:
        where = f"row {row_no}"
        for _, attr in _VALUES:
            v = getattr(c, attr)
            if not v:
                continue
            past = values.get(attr, {}).get(_canon(v))
            if past is not None and past != v:
                out.append(Finding("warn", "history_variant", where,
                                   f"{attr}={sanitize(v)!r} was {sanitize(past)!r} in earlier links; "
                                   "GA4 will report them separately"))
        if c.url:
            try:
                u = build_url(c)
            except ValueError:
                continue
            if u in links:
                out.append(Finding("warn", "history_duplicate", where,
                                   f"same final URL as row {links[u]} of the history file"))
    return out
