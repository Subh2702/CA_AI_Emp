"""Tool belt for one unit of work (one inbox document). Every call is audited and, where it changes
external state, passed through the governance layer first."""
import json
import os
import re
import time

from . import config, governance, knowledge

MAX_AUTO_RETRIES = 2
MIN_ATTEMPTS_BEFORE_ESCALATING = 5
DISPOSITIONS = ["paid", "duplicate_skipped", "escalated", "not_an_invoice"]

SPECS = [
    {"name": "read_file", "description": "Read a document from the company folder, e.g. inbox/01_x.txt.",
     "parameters": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}},
    {"name": "search_knowledge", "description": "Search company SOPs and policies for guidance.",
     "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}},
    {"name": "web_get", "description": "Open an ERP page (GET), e.g. /vendors, /pos, /bills, /bills/new, /bills/3.",
     "parameters": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}},
    {"name": "web_post", "description": "Submit an ERP form. 'path' is the form's action shown on the page and "
     "'fields' maps field names to values.",
     "parameters": {"type": "object", "properties": {"path": {"type": "string"}, "fields": {"type": "object"}},
                    "required": ["path", "fields"]}},
    {"name": "ask_human", "description": "Ask a human a question when something is ambiguous or you are blocked. Waits for the answer.",
     "parameters": {"type": "object", "properties": {"question": {"type": "string"}}, "required": ["question"]}},
    {"name": "finish_invoice", "description": "Report the final outcome for this document. Call exactly once when done.",
     "parameters": {"type": "object", "properties": {
         "disposition": {"type": "string", "enum": DISPOSITIONS,
                         "description": "paid | duplicate_skipped | escalated (not processed, needs a human) | not_an_invoice"},
         "vendor": {"type": "string"}, "invoice_no": {"type": "string"}, "amount": {"type": "number"},
         "bill_id": {"type": "integer", "description": "ERP bill id if a bill was created/paid"},
         "reason": {"type": "string", "description": "One or two sentences of evidence/justification"}},
         "required": ["disposition", "reason"]}},
]


class TaskTools:
    def __init__(self, invoice_key, browser, gate, audit, inbox_dir):
        self.key, self.browser, self.gate, self.audit = invoice_key, browser, gate, audit
        self.inbox_dir = inbox_dir
        self.created, self.paid = set(), set()
        self.post_failures, self.last_post_failed = 0, False
        self.result = None
        self.forms = {}   # action -> field names, for every form actually seen on a page
        self.docs = []    # text of every document read
        self.pages = []   # text of every page read (evidence for claims)

    def call(self, name, args):
        self.audit.log("tool_call", invoice=self.key, tool=name, args=args)
        try:
            fn = getattr(self, "t_" + name, None)
            if not fn:
                out = f"ERROR: unknown tool '{name}'. Available: " + ", ".join(s["name"] for s in SPECS)
            else:
                out = fn(**args)
        except TypeError as e:
            out = f"ERROR: bad arguments for {name}: {e}"
        except Exception as e:  # tool failure must be visible to the model, never crash the run
            out = f"ERROR: {type(e).__name__}: {e}"
        out = str(out)
        self.audit.log("tool_result", invoice=self.key, tool=name, result=out[:1500])
        return out[:3500]

    def t_read_file(self, path):
        if path.startswith("inbox/"):
            base, rel = self.inbox_dir, path[len("inbox/"):]
        else:
            base, rel = os.path.join(config.COMPANY_DIR, "knowledge"), path.removeprefix("knowledge/")
        full = os.path.realpath(os.path.join(base, rel))
        if not full.startswith(os.path.realpath(base) + os.sep):
            return "ERROR: access outside the permitted folders (inbox/, knowledge/) is not permitted"
        if not os.path.isfile(full):
            return f"ERROR: no such file: {path}"
        text = open(full).read()
        if path.startswith("inbox/"):
            self.docs.append(text)
        return text

    def t_search_knowledge(self, query):
        return "\n\n".join(knowledge.search(query))

    def t_web_get(self, path):
        status, final, text, title = self.browser.open(path)
        for f in self.browser.last_forms:
            self.forms[f["action"]] = f["names"]
        self.pages.append(text)
        return f"HTTP {status} {final}\n{text}"

    def t_web_post(self, path, fields):
        if isinstance(fields, str):
            fields = json.loads(fields)
        fields = {k: str(v) for k, v in fields.items()}
        if path not in self.forms:
            return (f"ERROR (nothing submitted): you have not seen a form that submits to '{path}'. Open the page "
                    f"containing the form first and use the action shown in its [FORM ...] line. "
                    f"Form actions seen so far: {sorted(self.forms) or 'none'}")
        names = self.forms[path]
        unknown = [k for k in fields if k not in names]
        missing = [n for n in names if n not in fields and n not in ("approved_by", "currency")]
        if unknown or missing:
            return (f"ERROR (nothing submitted): the form at {path} has fields {names}. "
                    f"Unknown fields: {unknown or 'none'}. Missing fields: {missing or 'none'}.")
        verdict = governance.evaluate_post(path, fields)
        self.audit.log("governance", invoice=self.key, path=path, action=verdict.action, reason=verdict.reason or verdict.approval_summary)
        if verdict.action == "deny":
            return f"BLOCKED BY POLICY (nothing was submitted): {verdict.reason}"
        if verdict.action == "needs_approval":
            decision, note, approver = self.gate.request(verdict.approval_kind, verdict.approval_summary, self.key)
            if decision != "approve":
                return f"HUMAN DENIED this action (nothing was submitted). Note from human: {note or 'none'}"
            if path.endswith("/pay"):
                fields["approved_by"] = approver  # identity comes from the approval record, never from the model
        elif path.endswith("/pay"):
            fields["approved_by"] = ""
        status, final, text, title = self.browser.open(path, fields)
        for attempt in range(MAX_AUTO_RETRIES):
            if status < 500:
                break
            # Transient server error: outcome unknown. Reconcile against the system of record, then retry only if absent.
            self.post_failures += 1
            self.audit.log("recovery", invoice=self.key, note=f"HTTP {status} on {path}; reconciling before retry {attempt + 1}")
            if self._already_saved(path, fields):
                return (f"HTTP {status} was returned, but the harness checked /bills and the record WAS saved. "
                        f"Do not resubmit; open /bills to find its id and continue.")
            time.sleep(0.5 * (attempt + 1))
            status, final, text, title = self.browser.open(path, fields)
        for f in self.browser.last_forms:
            self.forms[f["action"]] = f["names"]
        self.pages.append(text)
        self.last_post_failed = status >= 500
        if status >= 500:
            self.post_failures += 1
            return (f"HTTP {status} from ERP: the request FAILED even after {MAX_AUTO_RETRIES} automatic retries "
                    f"(nothing was saved as far as /bills shows). The outage may be temporary: try again; "
                    f"do not give up before {MIN_ATTEMPTS_BEFORE_ESCALATING} failed attempts.\n{text}")
        m = re.search(r"SUCCESS BANNER: (Bill #(\d+) created|Payment #\d+ recorded)", text)
        if m and m.group(2):
            self.created.add(int(m.group(2)))
        elif m:
            bid = re.search(r"# Bill #(\d+)", text)
            if bid:
                self.paid.add(int(bid.group(1)))
        if "BANNER" not in text:
            text += "\nNOTE: no SUCCESS banner appeared, so this was NOT saved."
        return f"HTTP {status} {final}\n{text}"

    def _already_saved(self, path, fields):
        if path != "/bills/create":
            return False
        _, _, page, _ = self.browser.open("/bills")
        row = re.compile(rf"\|\s*{re.escape(fields.get('vendor_id', ''))}\s*\|\s*{re.escape(fields.get('invoice_no', ''))}\s*\|")
        return any(row.search(line) for line in page.splitlines())

    def t_ask_human(self, question):
        decision, note, _ = self.gate.request("question", question, self.key)
        return f"Human answered: {note or decision}"

    def t_finish_invoice(self, disposition, reason, vendor="", invoice_no="", amount=None, bill_id=None):
        if disposition not in DISPOSITIONS:
            return f"ERROR: disposition must be one of {DISPOSITIONS}"
        if disposition == "paid" and not self.paid:
            return ("REJECTED: you cannot report 'paid' because no successful payment was observed in this session. "
                    "Pay the bill on its page and confirm the SUCCESS banner, or choose another disposition.")
        if disposition == "paid" and bill_id and int(bill_id) not in self.paid:
            return f"REJECTED: bill #{bill_id} was not paid in this session (paid: {sorted(self.paid)})."
        if disposition == "escalated" and self.last_post_failed and self.post_failures < MIN_ATTEMPTS_BEFORE_ESCALATING:
            return (f"REJECTED: only {self.post_failures} failed attempts so far. ERP outages are usually transient: check /bills, "
                    f"then resubmit. SOP allows escalating an outage only after {MIN_ATTEMPTS_BEFORE_ESCALATING} failed attempts.")
        if disposition == "duplicate_skipped":
            if self.created or self.paid:
                return "REJECTED: you created/paid something in this session, so this is not a duplicate skip."
            if not invoice_no or not any(invoice_no in d for d in self.docs):
                return (f"REJECTED: invoice_no '{invoice_no}' does not appear in the document you were asked to process. "
                        "Re-read it; notes from earlier documents are not about this one.")
            if not any(invoice_no in p and "|" in p for p in self.pages):
                return ("REJECTED: provide the invoice_no and make sure you actually viewed the ERP /bills page showing "
                        "an existing bill with that invoice number before reporting a duplicate.")
        self.result = {"disposition": disposition, "vendor": vendor, "invoice_no": invoice_no, "amount": amount,
                       "bill_id": bill_id, "reason": reason, "created_bills": sorted(self.created),
                       "paid_bills": sorted(self.paid)}
        return "Recorded. Task complete."
