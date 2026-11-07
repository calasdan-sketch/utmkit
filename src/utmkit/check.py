"""Follow a tracked link's redirects and report whether the UTM parameters survive.

Many redirectors (link shorteners, http->https, www canonicalisation, geo or
login redirects) drop the query string; GA4 then sees the session with no
campaign. This is the one check a URL builder can't do offline.

Safety: only http/https; every hop's host is resolved and loopback / private /
link-local / reserved addresses are refused unless ``allow_private=True``
(there is a DNS-rebinding window between our check and the connection - do not
point this at untrusted spec files on a machine with sensitive internal
services). The response body is never read. JavaScript and ``<meta refresh>``
redirects are not followed, so those are reported as unverifiable.
"""
from __future__ import annotations

import http.client
import ipaddress
import socket
import ssl
from dataclasses import dataclass, field
from typing import Callable, List, Optional
from urllib.parse import urljoin, urlsplit

from .core import UTM_KEYS, _key, sanitize


@dataclass
class CheckResult:
    url: str
    ok: bool
    final_url: str = ""
    status: int = 0
    hops: List[str] = field(default_factory=list)
    lost: List[str] = field(default_factory=list)
    problem: str = ""


def _host_allowed(host: str, port: int, allow_private: bool) -> Optional[str]:
    if allow_private:
        return None
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except OSError as e:
        return f"cannot resolve {sanitize(host)}: {e}"
    for info in infos:
        ip = ipaddress.ip_address(info[4][0].split("%")[0])
        if ip.version == 6 and ip.ipv4_mapped is not None:
            ip = ip.ipv4_mapped
        if (ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved
                or ip.is_multicast or ip.is_unspecified):
            return f"{sanitize(host)} resolves to non-public address {ip}; use --allow-private to permit"
    return None


def _request(url: str, timeout: float):
    p = urlsplit(url)
    port = p.port or (443 if p.scheme == "https" else 80)
    path = (p.path or "/") + (f"?{p.query}" if p.query else "")
    if p.scheme == "https":
        conn = http.client.HTTPSConnection(p.hostname, port, timeout=timeout,
                                           context=ssl.create_default_context())
    else:
        conn = http.client.HTTPConnection(p.hostname, port, timeout=timeout)
    try:
        for method in ("HEAD", "GET"):
            conn.request(method, path, headers={"User-Agent": "utmkit-check/0.2",
                                                "Accept": "*/*"})
            resp = conn.getresponse()
            if method == "HEAD" and resp.status in (405, 501):
                resp.close()
                conn.close()
                conn.connect()
                continue
            return resp.status, resp.getheader("Location") or ""
        return 0, ""
    finally:
        conn.close()


def check_url(url: str, allow_private: bool = False, max_hops: int = 10,
              timeout: float = 10.0,
              fetch: Callable[[str, float], tuple] = _request) -> CheckResult:
    res = CheckResult(url=url, ok=False)
    want = {k for p in urlsplit(url).query.split("&") if (k := _key(p)) in UTM_KEYS}
    cur = url
    for _ in range(max_hops + 1):
        p = urlsplit(cur)
        if p.scheme not in ("http", "https") or not p.hostname:
            res.problem = f"refusing non-http(s) URL {sanitize(cur)[:100]!r}"
            return res
        bad = _host_allowed(p.hostname, p.port or (443 if p.scheme == "https" else 80),
                            allow_private)
        if bad:
            res.problem = bad
            return res
        res.hops.append(cur)
        try:
            status, loc = fetch(cur, timeout)
        except (OSError, http.client.HTTPException, ValueError) as e:
            res.problem = f"request failed: {sanitize(str(e))[:120]}"
            return res
        res.status, res.final_url = status, cur
        if status in (301, 302, 303, 307, 308) and loc:
            cur = urljoin(cur, loc)
            continue
        have = {k for pp in urlsplit(cur).query.split("&") if (k := _key(pp)) in UTM_KEYS}
        res.lost = sorted(want - have)
        if status >= 400:
            res.problem = f"final page returned HTTP {status}"
        elif res.lost:
            res.problem = "redirect chain dropped " + ", ".join(res.lost)
        res.ok = not res.problem
        return res
    res.problem = f"more than {max_hops} redirects"
    return res
