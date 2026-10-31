import re
import shutil
import subprocess
import unittest
import urllib.request
from pathlib import Path

from httpbase import HttpBase

STATIC = Path(__file__).resolve().parent.parent / "assembly_site" / "static"


class StaticAssetsTest(unittest.TestCase):
    def test_app_js_is_valid_javascript(self):
        if not shutil.which("node"):
            self.skipTest("node not installed")
        r = subprocess.run(["node", "--check", str(STATIC / "app.js")], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_no_dynamic_html_or_code_in_the_app(self):
        js = (STATIC / "app.js").read_text()
        for bad in ("innerHTML", "outerHTML", "insertAdjacentHTML", "eval(", "new Function", "document.write", "setAttribute(\"style\""):
            self.assertNotIn(bad, js, "app.js must not use %s (record text is inserted as text only)" % bad)

    def test_index_has_no_inline_script_or_style(self):
        html = (STATIC / "index.html").read_text()
        self.assertNotRegex(html, r"<script(?![^>]*\bsrc=)[^>]*>")
        self.assertNotRegex(html, r"\sstyle=")
        self.assertNotRegex(html, r"<style")
        self.assertNotRegex(html, r"\son[a-z]+=")


class CspTest(HttpBase, unittest.TestCase):
    def test_security_headers_on_pages_and_api(self):
        for path in ("/", "/app.js", "/api/summary"):
            with urllib.request.urlopen(self.base + path) as r:
                csp = r.headers["Content-Security-Policy"]
                self.assertIn("default-src 'self'", csp)
                self.assertIn("frame-ancestors 'none'", csp)
                self.assertNotIn("unsafe-inline", csp)
                self.assertNotIn("unsafe-eval", csp)
                self.assertEqual(r.headers["X-Content-Type-Options"], "nosniff")
                self.assertEqual(r.headers["Cache-Control"], "no-store")
                self.assertEqual(r.headers["Referrer-Policy"], "no-referrer")


def _lum(hexc):
    h = hexc.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    rgb = [int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    rgb = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in rgb]
    return 0.2126 * rgb[0] + 0.7152 * rgb[1] + 0.0722 * rgb[2]


def contrast(a, b):
    la, lb = sorted((_lum(a), _lum(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


class ContrastTest(unittest.TestCase):
    """WCAG AA (4.5:1) for every text/background pair the stylesheet defines, in light and dark mode."""
    css = (STATIC / "style.css").read_text()

    def tokens(self, block):
        return dict(re.findall(r"--([a-z-]+):(#[0-9a-fA-F]{3,6})", block))

    def themes(self):
        light = self.tokens(re.search(r":root\{([^}]*)\}", self.css).group(1))
        dark = dict(light)
        dark.update(self.tokens(re.search(r"prefers-color-scheme:dark\)\{:root\{([^}]*)\}", self.css).group(1)))
        return {"light": light, "dark": dark}

    def test_text_pairs_meet_aa(self):
        pairs = [("ink", "bg"), ("ink", "card"), ("ink", "code"), ("mute", "bg"), ("mute", "card"), ("mute", "code"),
                 ("acc", "card"), ("acc", "bg"), ("acc-ink", "acc"), ("ok", "card"), ("warn", "card"), ("bad", "card"),
                 ("warn", "code"), ("bad", "bg")]
        for name, t in self.themes().items():
            for fg, bg in pairs:
                self.assertGreaterEqual(contrast(t[fg], t[bg]), 4.5, "%s: %s on %s is %.2f" % (name, fg, bg, contrast(t[fg], t[bg])))
