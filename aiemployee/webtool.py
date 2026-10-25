"""A browser-like client for web apps: cookies, redirects, re-login on session expiry, and a
text rendering of pages (headings, tables, links, forms, banners) that a model can read and act on.
Everything it does goes over real HTTP to the live application."""
import http.cookiejar
import re
import urllib.error
import urllib.parse
import urllib.request
from html.parser import HTMLParser

from . import config


class _Render(HTMLParser):
    def __init__(self):
        super().__init__()
        self.out, self.row, self.cur, self.form = [], None, None, None
        self.flash = None
        self.skip = 0
        self.select = None
        self.buf = ""
        self.title = ""
        self.in_title = False
        self.href = None
        self.forms = []

    def handle_starttag(self, tag, a):
        a = dict(a)
        if tag in ("script", "style", "nav"):
            self.skip += 1
        if tag == "title":
            self.in_title = True
        if tag == "tr":
            self.row = []
        if tag in ("td", "th"):
            self.cur = ""
        if tag == "div" and "flash" in (a.get("class") or ""):
            self.flash = "err" if "err" in a["class"] else "ok"
            self.buf = ""
        if tag == "a" and a.get("href") and not self.skip:
            self.href = a["href"]
            self.buf = ""
        if tag == "form":
            self.form = {"action": a.get("action", ""), "method": (a.get("method") or "get").upper(), "fields": []}
        if tag == "input" and self.form is not None:
            self.form["fields"].append(f"{a.get('name')}" + (f" (default '{a['value']}')" if a.get("value") else ""))
            self.form.setdefault("names", []).append(a.get("name"))
        if tag == "select" and self.form is not None:
            self.select = {"name": a.get("name"), "opts": []}
        if tag == "option" and self.select is not None:
            self.select["opts"].append(a.get("value"))
            self.opt_label = True
            self.buf = ""
        if tag in ("h1", "p"):
            self.buf = ""

    def handle_endtag(self, tag):
        if tag in ("script", "style", "nav"):
            self.skip -= 1
        if tag == "title":
            self.in_title = False
        if tag in ("td", "th") and self.row is not None:
            self.row.append(self.cur.strip())
            self.cur = None
        if tag == "tr" and self.row is not None:
            self.out.append(" | ".join(self.row))
            self.row = None
        if tag == "div" and self.flash:
            kind = "ERROR" if self.flash == "err" else "SUCCESS"
            self.out.append(f"*** {kind} BANNER: {self.buf.strip()} ***")
            self.flash = None
        if tag == "h1":
            self.out.append("# " + self.buf.strip())
        if tag == "p":
            self.out.append(self.buf.strip())
        if tag == "a" and self.href:
            self.out.append(f"[link] {self.buf.strip()} -> {self.href}")
            self.href = None
        if tag == "option" and self.select is not None and self.select["opts"]:
            self.select["opts"][-1] = f"{self.select['opts'][-1]}" + (f" [{self.buf.strip()}]" if self.buf.strip() and self.buf.strip() != self.select["opts"][-1] else "")
        if tag == "select" and self.select:
            self.form["fields"].append(f"{self.select['name']} (choose one of: {', '.join(self.select['opts'])})")
            self.form.setdefault("names", []).append(self.select["name"])
            self.select = None
        if tag == "form" and self.form:
            self.out.append(f"[FORM {self.form['method']} {self.form['action']}] fields: " + "; ".join(self.form["fields"]))
            self.forms.append({"action": self.form["action"], "method": self.form["method"], "names": self.form.get("names", [])})
            self.form = None

    def handle_data(self, d):
        if self.skip:
            return
        if self.in_title:
            self.title += d
        if self.cur is not None:
            self.cur += d
        self.buf += d


def render(html_text):
    r = _Render()
    r.feed(html_text)
    return "\n".join(x for x in r.out if x), r.title, r.forms


class Browser:
    def __init__(self, base=None, user=None, password=None, audit=None):
        self.base = base or config.ERP_URL
        self.user, self.password = user or config.ERP_USER, password or config.ERP_PASSWORD
        self.audit = audit
        self.jar = http.cookiejar.CookieJar()
        self.op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.jar))
        self.logged_in = False
        self.last_forms = []

    def _req(self, path, data=None):
        url = path if path.startswith("http") else self.base + path
        if not url.startswith(self.base):
            raise ValueError("Navigation outside the allowed application is not permitted")
        body = urllib.parse.urlencode(data).encode() if data is not None else None
        try:
            with self.op.open(urllib.request.Request(url, body), timeout=30) as r:
                return r.status, r.geturl(), r.read().decode(errors="replace")
        except urllib.error.HTTPError as e:
            return e.code, url, e.read().decode(errors="replace")

    def _login(self):
        self._req("/login", {"username": self.user, "password": self.password})
        if self.audit:
            self.audit.log("recovery", note="ERP session expired; re-authenticated automatically")

    def open(self, path, data=None):
        """Returns (status, final_path, text, title)."""
        if not self.logged_in:
            self._req("/login", {"username": self.user, "password": self.password})
            self.logged_in = True
        status, url, text = self._req(path, data)
        if urllib.parse.urlparse(url).path == "/login" and path != "/login":
            self._login()
            status, url, text = self._req(path, data)
        rendered, title, forms = render(text)
        self.last_forms = forms
        return status, urllib.parse.urlparse(url).path, rendered, title
