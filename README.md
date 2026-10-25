# AI Employee: autonomous Accounts Payable operator (PoC)

**Request in:** "Process this week's vendor invoices and get them paid."
**Out:** invoices billed and paid in a live ERP, with humans pulled in only for approvals/exceptions,
and an independently verified, auditable report.

## Run
```
python3 run.py            # starts the Acme ERP (:8001) and the console (:8080). Python stdlib only.
# open http://127.0.0.1:8080, pick "Local model (Ollama)" or "Hugging Face API", press Run
```
Local model: Ollama `qwen3:4b-instruct` (override with `OLLAMA_MODEL`). Frontier option:
`export HF_TOKEN=...` (model via `HF_MODEL`). Restart `run.py` to reset the ERP data.

## Architecture
| Stage | What happens | Code |
|---|---|---|
| Understand | LLM resolves the vague request against company SOPs/policies into a work order (interpretation, procedure, approval boundaries, done criteria) | `orchestrator.py`, `knowledge.py`, `company/knowledge/` |
| Plan | One governed work unit per inbox document | `orchestrator.py` |
| Execute / Observe / Adapt | Tool-calling loop per document: read file, browse ERP pages, submit forms; working memory carries across documents | `agent.py`, `tools.py`, `webtool.py` |
| Govern | Policy engine reads live ERP state and decides allow / needs-human / deny *outside the model*; approver identity is injected from the human approval record | `governance.py` |
| Verify | Independent verifier recomputes the policy-correct outcome from the source document + pre-run ERP state, compares to post-run ERP state and the agent's claim, and checks run-wide invariants | `verifier.py` |
| Audit | Append-only JSONL of every thought, tool call, policy decision, approval and recovery in `runs/<id>/`, plus `report.json` | `audit.py` |

The target is a real stateful web app (`erp/server.py`): login, expiring sessions, HTML forms, validation errors
shown as 200 pages, and an injected transient 503. The agent drives it over HTTP like a browser
(`webtool.py` renders pages to text with forms/links/banners). It is deliberately permissive (it will pay a blocked
vendor), so safety comes from SOPs + governance, not from the software.

## Test data (company/inbox)
clean invoice (should be paid) | $8,900 invoice (human approval) | blocked vendor (escalate) | duplicate reminder (skip) |
invoice 15% over PO (human exception) | newsletter (ignore) | messy-format invoice (should be paid)

## Reliability mechanisms (found by running a 4B local model against the real app)
- Claims need evidence: `finish_invoice(paid)` is rejected unless a SUCCESS banner for the payment was observed this session;
  `duplicate_skipped` requires having actually viewed the matching bill.
- POSTs only to forms the agent has actually seen, with exact field names; otherwise corrective errors (stops guessed endpoints).
- Unknown outcomes (503) are surfaced as unknown; the agent checks state before retrying (no double-billing).
- Expired sessions are re-authenticated transparently and logged. Stalls are retried once, then escalated to a human.

## Verified runs (local qwen3:4b-instruct)
- Approve-all: 5 actions correct, verification PASS (8,900 payment carries approver identity).
- Deny-all: Initech left unpaid (open bill), Hooli never billed, verification PASS.

## Known limits
- HTTP-level browsing, not pixel-level computer use; the same tool interface could be backed by Playwright.
- The verifier's invoice parser is regex-based and fits this document set; a production oracle would use a second model/OCR path.
- Single run at a time; no resume after crash; one company/workflow. Governance rules are code, not yet loaded from policy text.

## Scenarios (select in the UI, or run headless)
`python3 tests/run_scenarios.py [scenario ...] [--modes approve,deny]` runs packs against the live console and prints verifier results.
Packs in `company/scenarios/`: baseline (7 docs), edge_cases (9), adversarial (4), inbox_hygiene (5), chaos (4; repeated 503s + fast session expiry).
The ERP is reset (with the scenario's chaos settings) at the start of every run.

Latest local-model matrix (qwen3:4b-instruct, 10 runs): 7 PASS, 3 FAIL. Failures were different documents each time and
non-repeating (wrong label on a duplicate, a clean invoice escalated, a duplicate claimed on a clean invoice). None caused a wrong
payment, and the verifier flagged every one. Remaining misses are model reliability, not harness holes.
