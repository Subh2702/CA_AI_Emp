"""Governance layer: policy enforcement and human approvals that live OUTSIDE the model.

The model proposes actions; this layer decides allow / needs_approval / deny from live system state
(read through the ERP's read-only audit API, never from the model's claims). The model cannot bypass it:
approver identity for payments is injected here, not accepted from model-supplied fields.
"""
import json
import threading
import urllib.request

from . import config


def erp_state():
    req = urllib.request.Request(config.ERP_URL + "/api/state", headers={"X-Api-Key": config.ERP_API_KEY})
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read())


def reset_erp(chaos):
    req = urllib.request.Request(config.ERP_URL + "/api/reset", json.dumps(chaos).encode(),
                                 {"X-Api-Key": config.ERP_API_KEY, "Content-Type": "application/json"})
    urllib.request.urlopen(req, timeout=15).read()


class ApprovalGate:
    """Blocks the calling worker until a human answers in the UI."""

    def __init__(self, audit):
        self.audit = audit
        self.pending = {}
        self.lock = threading.Lock()
        self.n = 0
        self.auto = None  # "approve" | "deny" for headless tests only

    def request(self, kind, summary, invoice_key, detail=None):
        with self.lock:
            self.n += 1
            rid = f"A{self.n}"
            ev = threading.Event()
            self.pending[rid] = {"id": rid, "kind": kind, "summary": summary, "invoice": invoice_key,
                                 "detail": detail or {}, "event": ev, "decision": None, "note": ""}
        self.audit.log("approval_requested", id=rid, approval_kind=kind, summary=summary, invoice=invoice_key)
        if self.auto:
            if kind == "question":
                self.resolve(rid, "answer", "No further information is available. Escalate this document.", "test-harness")
            else:
                self.resolve(rid, self.auto, "auto (test mode)", "test-harness")
        ev.wait()
        p = self.pending[rid]
        return p["decision"], p["note"], p.get("approver")

    def resolve(self, rid, decision, note="", approver="AP Manager"):
        with self.lock:
            p = self.pending.get(rid)
            if not p or p["decision"]:
                return False
            p["decision"], p["note"], p["approver"] = decision, note, approver
        self.audit.log("approval_decision", id=rid, decision=decision, note=note, approver=approver,
                       invoice=p["invoice"], approval_kind=p["kind"])
        p["event"].set()
        return True

    def open_requests(self):
        return [{k: v for k, v in p.items() if k != "event"} for p in self.pending.values() if not p["decision"]]


class Verdict:
    def __init__(self, action, reason="", approval_kind=None, approval_summary=""):
        self.action, self.reason = action, reason
        self.approval_kind, self.approval_summary = approval_kind, approval_summary


def evaluate_post(path, fields):
    """Policy decision for a state-changing request the agent wants to make."""
    st = erp_state()
    vendors = {v["id"]: v for v in st["vendors"]}
    if path == "/bills/create":
        try:
            vid, amount = int(fields.get("vendor_id")), float(str(fields.get("amount", "")).replace(",", ""))
        except (TypeError, ValueError):
            return Verdict("allow")  # malformed input: the ERP will reject it, nothing to govern yet
        v = vendors.get(vid)
        if not v:
            return Verdict("allow")
        if v["status"] != "approved":
            return Verdict("deny", f"Vendor '{v['name']}' is {v['status']} ({v['note']}). Policy FIN-POL-07: "
                                   "blocked vendors may not be billed or paid by the AI employee. Escalate to Compliance.")
        if any(b["vendor_id"] == vid and b["invoice_no"].lower() == str(fields.get("invoice_no", "")).lower()
               for b in st["bills"]):
            return Verdict("deny", "A bill with this vendor and invoice number already exists (duplicate). Do not create it.")
        po = next((p for p in st["pos"] if p["po_number"] == fields.get("po_number")), None)
        if po and amount > po["amount"] * (1 + config.PO_TOLERANCE) + 1e-9:
            over = (amount / po["amount"] - 1) * 100
            return Verdict("needs_approval", "", "po_exception",
                           f"Invoice {fields.get('invoice_no')} from {v['name']} is {amount:,.2f} but {po['po_number']} "
                           f"is {po['amount']:,.2f} ({over:.1f}% over, tolerance 2%). Approve creating the bill anyway?")
        return Verdict("allow")
    if path.startswith("/bills/") and path.endswith("/pay"):
        try:
            bid = int(path.split("/")[2])
        except ValueError:
            return Verdict("allow")
        b = next((b for b in st["bills"] if b["id"] == bid), None)
        if not b:
            return Verdict("allow")
        v = vendors[b["vendor_id"]]
        if v["status"] != "approved":
            return Verdict("deny", f"Vendor '{v['name']}' is {v['status']}; payment forbidden by FIN-POL-07.")
        if b["status"] != "open":
            return Verdict("deny", f"Bill #{bid} is already {b['status']}; paying again would be a duplicate payment.")
        if b["amount"] > config.APPROVAL_THRESHOLD:
            return Verdict("needs_approval", "", "high_value_payment",
                           f"Pay bill #{bid} ({v['name']}, invoice {b['invoice_no']}) for ${b['amount']:,.2f}. "
                           f"Payments over ${config.APPROVAL_THRESHOLD:,.0f} need AP manager approval.")
    return Verdict("allow")
