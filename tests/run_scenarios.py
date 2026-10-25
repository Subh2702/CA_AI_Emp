"""Headless regression: run scenarios against the live console (python3 run.py must be running).
usage: python3 tests/run_scenarios.py [--provider ollama|huggingface] [scenario ...] [--modes approve,deny]"""
import argparse
import json
import time
import urllib.request

BASE = "http://127.0.0.1:8080"


def call(path, body=None):
    req = urllib.request.Request(BASE + path, json.dumps(body).encode() if body is not None else None)
    return json.load(urllib.request.urlopen(req))


ap = argparse.ArgumentParser()
ap.add_argument("scenarios", nargs="*")
ap.add_argument("--provider", default="ollama")
ap.add_argument("--modes", default="approve,deny")
args = ap.parse_args()
names = args.scenarios or [s["id"] for s in call("/api/scenarios")]
rows, failed = [], False
for sc in names:
    for mode in args.modes.split(","):
        t0 = time.time()
        call("/api/run", {"request": "Process this week's vendor invoices and get them paid.", "provider": args.provider,
                          "scenario": sc, "auto": mode})
        while True:
            r = call("/api/poll?since=999999")["run"]
            if r["status"] in ("done", "error"):
                break
            time.sleep(3)
        rep = r["report"]
        bad = [f"{i['file']}: {'; '.join(i['problems'])}" for i in rep["invoices"] if i["verified"] != "PASS"] if rep else ["run error"]
        bad += [c["check"] for c in (rep or {}).get("invariants", []) if not c["ok"]]
        failed |= bool(bad)
        rows.append((sc, mode, rep["verification"] if rep else "ERROR", f"{time.time()-t0:.0f}s", bad))
        print(f"{sc:14} {mode:8} {rows[-1][2]:6} {rows[-1][3]:>5}", *(["\n    - " + b for b in bad]), flush=True)
raise SystemExit(1 if failed else 0)
