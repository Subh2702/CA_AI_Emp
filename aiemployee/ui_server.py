import base64
import hmac
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import config
from .orchestrator import Run

CURRENT = {"run": None}
INDEX = os.path.join(config.ROOT, "ui", "index.html")


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _json(self, obj, code=200):
        data = json.dumps(obj, default=str).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _authorized(self):
        if not config.UI_PASSWORD:
            return True
        got = self.headers.get("Authorization", "")
        want = "Basic " + base64.b64encode(f"{config.UI_USER}:{config.UI_PASSWORD}".encode()).decode()
        if hmac.compare_digest(got, want):
            return True
        self.send_response(401)
        self.send_header("WWW-Authenticate", 'Basic realm="AI Employee Console"')
        self.send_header("Content-Length", "0")
        self.end_headers()
        return False

    def do_GET(self):
        path, _, qs = self.path.partition("?")
        if path == "/healthz":
            return self._json({"ok": True})
        if not self._authorized():
            return
        run = CURRENT["run"]
        if path == "/":
            data = open(INDEX, "rb").read()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        elif path == "/api/config":
            self._json({"provider": config.DEFAULT_PROVIDER, "allow_auto": config.ALLOW_AUTO})
        elif path == "/api/scenarios":
            out = []
            for name in sorted(os.listdir(config.SCENARIOS_DIR)):
                m = json.load(open(os.path.join(config.SCENARIOS_DIR, name, "scenario.json")))
                out.append({"id": name, "title": m["title"], "description": m["description"],
                            "documents": len(os.listdir(os.path.join(config.SCENARIOS_DIR, name, "inbox")))})
            self._json(out)
        elif path == "/api/poll":
            since = int(dict(p.split("=") for p in qs.split("&") if "=" in p).get("since", 0))
            self._json({"run": run.snapshot() if run else None, "events": run.audit.since(since) if run else []})
        else:
            self._json({"error": "not found"}, 404)

    def do_POST(self):
        if not self._authorized():
            return
        n = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(n) or b"{}")
        if self.path == "/api/run":
            if CURRENT["run"] and CURRENT["run"].status in ("starting", "running"):
                return self._json({"error": "a run is already in progress"}, 409)
            CURRENT["run"] = Run(body.get("request", ""), body.get("provider", "ollama"), (body.get("auto") or None) if config.ALLOW_AUTO else None,
                                  body.get("scenario", "baseline"))
            CURRENT["run"].start()
            self._json({"ok": True, "id": CURRENT["run"].id})
        elif self.path == "/api/approval":
            run = CURRENT["run"]
            ok = bool(run) and run.gate.resolve(body["id"], body["decision"], body.get("note", ""), body.get("approver") or "AP Manager")
            self._json({"ok": ok})
        else:
            self._json({"error": "not found"}, 404)


def serve():
    srv = ThreadingHTTPServer((config.UI_HOST, config.UI_PORT), H)
    print(f"AI Employee console on http://{config.UI_HOST}:{config.UI_PORT}")
    srv.serve_forever()
