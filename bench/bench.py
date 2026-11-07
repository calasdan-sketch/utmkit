"""Reproducible benchmark: python bench/bench.py  (stdlib only; optional node for utm-builder).

1. foreign-param fidelity: share of 5000 seeded URLs whose NON-utm query survives byte-for-byte
2. batch throughput: rows/second for build+validate+slug on 20000 rows
3. defect detection: seeded spec mistakes caught (v0.1.0 logic vs now)
The v0.1.0 algorithms are copied below verbatim so the comparison is re-runnable.
"""
import json
import os
import random
import shutil
import subprocess
import sys
import tempfile
import time
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from utmkit import Campaign, build_url  # noqa: E402
from utmkit.batch import run_batch  # noqa: E402
from utmkit.core import validate_campaign, validate_rows  # noqa: E402


def legacy_build(url, **utm):  # utmkit 0.1.0
    parts = urlsplit(url)
    kept = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
            if not k.lower().startswith("utm_")]
    return urlunsplit((parts.scheme, parts.netloc, parts.path,
                       urlencode(kept + list(utm.items())), parts.fragment))


def corpus(n, seed=1):
    rnd = random.Random(seed)
    tricky = ["flag", "a=b%2Cc", "sig=a+b%3D%3D", "x=1;y=2", "p=%7Efoo/bar", "t=%E2%9C%93", "e=",
              "k=v", "tok=Zm9v%2Bbar%3D", "q=hello%20world", "r=a%2Fb"]
    out = []
    for _ in range(n):
        qs = rnd.sample(tricky, rnd.randint(1, 4))
        out.append("https://example.com/p?" + "&".join(qs))
    return out


def fidelity(urls):
    new = old = 0
    for u in urls:
        q = urlsplit(u).query
        if build_url(Campaign(u, source="s")).startswith(u.split("?")[0] + "?" + q + "&utm_"):
            new += 1
        if legacy_build(u, utm_source="s").startswith(u.split("?")[0] + "?" + q + "&utm_"):
            old += 1
    return old, new


def npm_fidelity(urls):
    node = shutil.which("node")
    mod = os.environ.get("UTM_BUILDER_DIR")  # dir holding node_modules/utm-builder
    if not (node and mod):
        return None
    js = ("const b=require('utm-builder');const u=JSON.parse(require('fs').readFileSync(0));"
          "console.log(JSON.stringify(u.map(x=>b(x,'s','m','c'))))")
    res = subprocess.run([node, "-e", js], input=json.dumps(urls), capture_output=True, text=True,
                         cwd=mod)
    if res.returncode:
        return None
    outs = json.loads(res.stdout)
    return sum(1 for u, o in zip(urls, outs) if o.startswith(u + "&utm_"))


def throughput(n=20000):
    rows = [(i, Campaign(f"https://ex.com/{i}?ref=nav", source="newsletter", medium="email",
                         campaign="launch-26", name=f"Ad {i % 50}")) for i in range(n)]
    d = tempfile.mkdtemp()
    t = time.perf_counter()
    run_batch(rows, d, ga4=True)
    dt = time.perf_counter() - t
    shutil.rmtree(d)
    # v0.1.0 slug allocation (list scan, restarting at -2 each time) on 1500 identical names
    from utmkit.core import unique_slug
    t = time.perf_counter()
    taken = []
    for _ in range(1500):
        taken.append(unique_slug("ad", taken))
    legacy = time.perf_counter() - t
    rows = [(i, Campaign(f"https://ex.com/{i}", source="a", medium="email", campaign="c", name="ad"))
            for i in range(1500)]
    d = tempfile.mkdtemp()
    t = time.perf_counter()
    run_batch(rows, d)
    shutil.rmtree(d)
    return n / dt, legacy, time.perf_counter() - t


def detection():
    seeded = [  # (campaign, defect id)
        (Campaign("javascript:alert(1)", source="a"), "bad_scheme"),
        (Campaign("https://a.com", source="a", medium="qr", campaign="c"), "ga4_unassigned"),
        (Campaign("https://a.com", source="a", medium="email"), "no_campaign"),
        (Campaign("https://a.com", source="a", campaign="c"), "no_medium"),
        (Campaign("https://a.com", source="a\x1b[31m", medium="email", campaign="c"), "bad_value_chars"),
        (Campaign("https://a.com/?utm_source=x", source="y", medium="email", campaign="c"), "overrides_existing"),
        (Campaign("https://a.com", source="spring%20sale", medium="email", campaign="c"), "pre_encoded"),
    ]
    pairs = [(Campaign("https://a.com", source="Instagram", medium="social", campaign="c"),
              Campaign("https://b.com", source="instagram", medium="social", campaign="c"), "case_variants"),
             (Campaign("https://a.com", source="a", medium="paid-social", campaign="c"),
              Campaign("https://b.com", source="a", medium="paid_social", campaign="c"), "near_duplicate"),
             (Campaign("https://a.com", source="a", medium="email", campaign="c"),
              Campaign("https://a.com", source="a", medium="email", campaign="c"), "duplicate_link")]
    total = len(seeded) + len(pairs)
    # v0.1.0 emitted only: no_url, no_source, not_lowercase, has_spaces, unusual_medium, no_scheme
    old_codes = {"no_url", "no_source", "not_lowercase", "has_spaces", "unusual_medium", "no_scheme"}
    old = sum(1 for _, d in seeded if d in old_codes) + sum(1 for *_, d in pairs if d in old_codes)
    new = sum(1 for c, d in seeded if any(f.code == d for f in validate_campaign(c, ga4=True)))
    new += sum(1 for a, b, d in pairs if any(f.code == d for f in validate_rows([(2, a), (3, b)])))
    return old, new, total


if __name__ == "__main__":
    urls = corpus(5000)
    o, n = fidelity(urls)
    print(f"foreign-param fidelity (5000 URLs): utmkit 0.1.0 {o / 50:.1f}%  utmkit now {n / 50:.1f}%")
    nb = npm_fidelity(urls)
    print("utm-builder (npm) fidelity:", "skipped (set UTM_BUILDER_DIR; needs node)" if nb is None
          else f"{nb / 50:.1f}%")
    rps, legacy_s, new_s = throughput()
    print(f"batch throughput: {rps:,.0f} rows/s (20k rows, build+validate+slug); "
          f"1500 identical names: 0.1.0 slug allocation alone {legacy_s:.2f}s, whole batch now {new_s:.2f}s")
    old, new, total = detection()
    print(f"seeded-defect detection: utmkit 0.1.0 {old}/{total}  now {new}/{total}")
