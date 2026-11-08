"""Mutation-style sanity check: break one key condition at a time in a scratch COPY of src/
and confirm the test suite notices.  python bench/mutants.py  (needs pytest; ~2 minutes).
Survivors are listed honestly: each one is a gap in the tests."""
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

MUTANTS = [
    ("core.py", "_key(p) not in UTM_KEYS", "_key(p) in UTM_KEYS", "managed utm keys are replaced, not kept"),
    ("core.py", 'out.append(quote(value[last:m.start()], safe=""))', 'out.append(value[last:m.start()])', "text around placeholders is encoded"),
    ("core.py", '"&amp;" in sp_query', '"&amq;" in sp_query', "HTML-entity ampersand caught"),
    ("core.py", 'if "\\\\" in url_head(c.url):', 'if "\\\\\\\\" in url_head(c.url):', "backslash URL caught"),
    ("core.py", "if value != value.lower():", "if value == value.lower():", "uppercase warning"),
    ("core.py", "MAX_SLUG = 80", "MAX_SLUG = 400", "slug length cap"),
    ("core.py", "if has_macro(value):\n            out.append(Finding(\"info\"", "if False:\n            out.append(Finding(\"info\"", "placeholder noticed"),
    ("check.py", "return ip.is_global and not ip.is_multicast", "return not ip.is_private", "non-public addresses refused"),
    ("check.py", '"\\\\" in url_head(cur) or', 'False and "\\\\" in url_head(cur) or', "redirect to backslash URL refused"),
    ("batch.py", '("=", "+", "-", "@", "\\t", "\\r")', '("+", "-", "@", "\\t", "\\r")', "CSV formula injection guard"),
    ("cli.py", '{"error": "error", "warn": "warning"}', '{"error": "error", "warn": "error"}', "GitHub annotation levels"),
    ("cli.py", "return 1 if any(f.severity == \"error\" for f in findings)", "return 0 if any(f.severity == \"error\" for f in findings)", "validate exit code"),
    ("channels.py", 'if m in ("referral", "app", "link"):', 'if m in ("referral", "app"):', "GA4 Referral rule"),
    ("channels.py", 'if m == "affiliate":', 'if m == "affiliates":', "GA4 Affiliates rule"),
    ("taxonomy.py", "        if has_macro(v):  # resolved", "        if False:  # resolved", "taxonomy skips placeholders"),
]


def main():
    survivors = []
    for fname, old, new, why in MUTANTS:
        tmp = tempfile.mkdtemp(prefix="utmkit-mut-")
        try:
            shutil.copytree(os.path.join(ROOT, "src"), os.path.join(tmp, "src"),
                            ignore=shutil.ignore_patterns("__pycache__", "*.egg-info"))
            path = os.path.join(tmp, "src", "utmkit", fname)
            with open(path, encoding="utf-8") as fh:
                text = fh.read()
            if text.count(old) != 1:
                print(f"BAD MUTANT (pattern found {text.count(old)}x): {fname}: {old[:50]}")
                survivors.append(why + " [mutant did not apply]")
                continue
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(text.replace(old, new))
            env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
            r = subprocess.run([sys.executable, "-m", "pytest", "-x", "-q", "-p", "no:cacheprovider",
                                "-o", f"pythonpath={os.path.join(tmp, 'src')}", os.path.join(ROOT, "tests")],
                               capture_output=True, text=True, env=env, cwd=tmp)
            killed = r.returncode != 0
            print(("killed  " if killed else "SURVIVED") + f" {fname}: {why}")
            if not killed:
                survivors.append(why)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    print(f"{len(MUTANTS) - len(survivors)}/{len(MUTANTS)} mutants killed")
    return 1 if survivors else 0


if __name__ == "__main__":
    sys.exit(main())
