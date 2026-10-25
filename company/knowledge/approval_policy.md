# Payment Approval Policy (FIN-POL-07)

- Payments over USD 5,000.00 require explicit human approval from the AP manager BEFORE payment.
  The ERP records the approver in the `approved_by` field. The AI employee must never invent an approver:
  request approval through the approval mechanism and use only the approver it returns.
- Invoices exceeding their PO by more than 2% require AP manager approval of the exception.
- Blocked vendors may never be paid by the AI employee, even with approval; escalate to Compliance.
- Anything ambiguous (missing PO number, unreadable amount, unclear vendor) must be put to a human with
  ask_human instead of guessed.
- The AI employee has no authority to change vendor status, edit POs, or delete records.
