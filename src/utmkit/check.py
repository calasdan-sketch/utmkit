"""Follow a tracked link's redirects and report whether the UTM parameters survive.

Many redirectors (link shorteners, http->https, www canonicalisation, geo or
login redirects) drop the query string; GA4 then sees the session with no
campaign. This is the one check a URL builder can't do offline.

Safety: only http/https; every hop's host is resolved once, every address must
be globally routable (loopback, private, link-local, carrier-grade NAT,
reserved... are refused) unless ``allow_private=True``, and the connection is
made to that already-checked address (no second DNS lookup, so no DNS-rebinding
window). Injected ``fetch`` callables are responsible for their own safety.
The response body is never read. JavaScript and ``<meta refresh>``
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
    changed: List[str] = field(default_factory=list)
    lost_at: int = 0  # index in ``hops`` of the first URL that no longer had every utm_*
    problem: str = ""


_NAT64 = ipaddress.ip_network("64:ff9b::/96")


def _public(ip) -> bool:
    if ip.version == 6 and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    if ip.version == 6 and ip.sixtofour is not None:
        return _public(ip.sixtofour)
    if ip.version == 6 and ip in _NAT64:  # RFC 6052 well-known prefix embeds an IPv4 address
        return _public(ipaddress.IPv4Address(ip.packed[-4:]))
    return ip.is_global and not ip.is_multicast


def _resolve(host: str, port: int, allow_private: bool):
    """Resolve once; returns (list of ip strings, problem). Refuses non-public addresses."""
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except (OSError, UnicodeError) as e:
        return [], f"cannot resolve {sanitize(host)}: {sanitize(str(e))[:80]}"
    ips = []
    for info in infos:
        text = info[4][0].split("%")[0]
        ip = ipaddress.ip_address(text)
        if not allow_private and not _public(ip):
            return [], f"{sanitize(host)} resolves to non-public address {ip}; use --allow-private to permit"
        ips.append(text)
    return ips, None


def _host_allowed(host: str, port: int, allow_private: bool) -> Optional[str]:
    if allow_private:
        return None
    return _resolve(host, port, False)[1]


def _connect(ip: str, port: int, timeout: float):
    return socket.create_connection((ip, port), timeout=timeout)


class _PinnedHTTP(http.client.HTTPConnection):
    def __init__(self, host, port, ip, timeout):
        super().__init__(host, port, timeout=timeout)
        self._ip = ip

    def connect(self):
        self.sock = _connect(self._ip, self.port, self.timeout)


class _PinnedHTTPS(http.client.HTTPSConnection):
    def __init__(self, host, port, ip, timeout):
        super().__init__(host, port, timeout=timeout, context=ssl.create_default_context())
        self._ip = ip

    def connect(self):
        sock = _connect(self._ip, self.port, self.timeout)
        self.sock = self._context.wrap_socket(sock, server_hostname=self.host)


def _make_fetch(allow_private: bool) -> Callable[[str, float], tuple]:
    def fetch(url: str, timeout: float):
        p = urlsplit(url)
        port = p.port or (443 if p.scheme == "https" else 80)
        ips, problem = _resolve(p.hostname, port, allow_private)
        if problem:
            raise OSError(problem)
        path = (p.path or "/") + (f"?{p.query}" if p.query else "")
        last: Exception = OSError("no address")
        for ip in ips:
            cls = _PinnedHTTPS if p.scheme == "https" else _PinnedHTTP
            conn = cls(p.hostname, port, ip, timeout)
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
            except (OSError, http.client.HTTPException) as e:
                last = e
            finally:
                conn.close()
        raise last
    return fetch


def _request(url: str, timeout: float):  # kept for callers that used the 0.2 name
    return _make_fetch(False)(url, timeout)


def _utms(url: str) -> dict:
    out = {}
    for pp in urlsplit(url).query.split("&"):
        k = _key(pp)
        if k in UTM_KEYS:
            out.setdefault(k, pp.split("=", 1)[1] if "=" in pp else "")
    return out


def check_url(url: str, allow_private: bool = False, max_hops: int = 10,
              timeout: float = 10.0,
              fetch: Optional[Callable[[str, float], tuple]] = None) -> CheckResult:
    res = CheckResult(url=url, ok=False)
    if fetch is None:
        fetch = _make_fetch(allow_private)
    sent = _utms(url)
    want = set(sent)
    cur = url
    for _ in range(max_hops + 1):
        try:
            p = urlsplit(cur)
            port = p.port or (443 if p.scheme == "https" else 80)
        except ValueError:
            res.problem = f"redirect to a malformed URL {sanitize(cur)[:100]!r}"
            return res
        if p.scheme not in ("http", "https") or not p.hostname:
            res.problem = f"refusing non-http(s) URL {sanitize(cur)[:100]!r}"
            return res
        bad = _host_allowed(p.hostname, port, allow_private)
        if bad:
            res.problem = bad
            return res
        if res.hops and not res.lost_at and want - set(_utms(cur)):
            res.lost_at = len(res.hops)
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
        got = _utms(cur)
        res.lost = sorted(want - set(got))
        res.changed = sorted(k for k in want & set(got) if got[k] != sent[k])
        if status >= 400:
            res.problem = f"final page returned HTTP {status}"
        elif res.lost:
            where = ""
            if res.lost_at:
                where = f" (first lost at hop {res.lost_at}: {sanitize(res.hops[res.lost_at])[:80]})"
            res.problem = "redirect chain dropped " + ", ".join(res.lost) + where
        elif res.changed:
            res.problem = "redirect chain rewrote the value of " + ", ".join(res.changed)
        res.ok = not res.problem
        return res
    res.problem = f"more than {max_hops} redirects"
    return res


def check_many(urls, allow_private: bool = False, timeout: float = 10.0, workers: int = 8,
               per_host: int = 2, fetch=None) -> List[CheckResult]:
    """Check many URLs concurrently, results in input order.

    At most ``per_host`` requests run at once against the same host (be polite to the
    destination), and one URL blowing up cannot take the whole run down.
    """
    import threading
    from concurrent.futures import ThreadPoolExecutor

    gates: dict = {}
    lock = threading.Lock()

    def gate(url: str):
        try:
            host = (urlsplit(url).hostname or "").lower()
        except ValueError:
            host = ""
        with lock:
            return gates.setdefault(host, threading.BoundedSemaphore(max(1, per_host)))

    def one(url: str) -> CheckResult:
        try:
            with gate(url):
                return check_url(url, allow_private, timeout=timeout, fetch=fetch)
        except Exception as e:  # noqa: BLE001 - report, never abort the batch
            return CheckResult(url=url, ok=False, problem=f"check failed: {sanitize(str(e))[:120]}")

    with ThreadPoolExecutor(max_workers=max(1, min(workers, 32))) as ex:
        return list(ex.map(one, urls))
