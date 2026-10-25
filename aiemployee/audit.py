import json
import os
import threading
import time


class Audit:
    """Append-only event log: in memory for the UI, JSONL on disk for evidence."""

    def __init__(self, run_dir):
        os.makedirs(run_dir, exist_ok=True)
        self.path = os.path.join(run_dir, "audit.jsonl")
        self.events = []
        self.lock = threading.Lock()

    def log(self, kind, **data):
        ev = {"i": len(self.events), "ts": round(time.time(), 2), "kind": kind, **data}
        with self.lock:
            ev["i"] = len(self.events)
            self.events.append(ev)
            with open(self.path, "a") as f:
                f.write(json.dumps(ev, default=str) + "\n")
        return ev

    def since(self, n):
        with self.lock:
            return self.events[n:]
