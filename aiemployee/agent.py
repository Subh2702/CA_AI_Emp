"""The act-observe-adapt loop for one unit of work."""
import json

from . import tools as T

MAX_STEPS = 24


def run_task(llm, system, user, tt, audit):
    msgs = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    seen, nudges = {}, 0
    for step in range(MAX_STEPS):
        resp = llm.chat(msgs, T.SPECS)
        if resp["content"].strip():
            audit.log("thought", invoice=tt.key, text=resp["content"].strip()[:600])
        if not resp["tool_calls"]:
            try:
                guess = json.loads(resp["content"].strip().strip("`").removeprefix("json").strip())
                if isinstance(guess, dict) and "disposition" in guess:
                    resp["tool_calls"] = [{"id": "shim", "name": "finish_invoice", "args": guess}]
                    audit.log("agent_note", invoice=tt.key, note="model answered in JSON text; treated as finish_invoice")
            except ValueError:
                pass
        if not resp["tool_calls"]:
            nudges += 1
            if nudges > 3:
                audit.log("agent_stalled", invoice=tt.key, step=step)
                return None
            msgs.append({"role": "assistant", "content": resp["content"]})
            msgs.append({"role": "user", "content": "Continue by calling a tool. When the document is fully handled, "
                                                    "call finish_invoice."})
            continue
        msgs.append({"role": "assistant", "content": resp["content"], "tool_calls": resp["tool_calls"]})
        for tc in resp["tool_calls"]:
            sig = tc["name"] + json.dumps(tc["args"], sort_keys=True)
            seen[sig] = seen.get(sig, 0) + 1
            out = tt.call(tc["name"], tc["args"])
            if seen[sig] >= 3 and tc["name"] != "finish_invoice":
                out += "\nWARNING: you have repeated this exact call 3 times. Change approach or escalate with finish_invoice."
            msgs.append({"role": "tool", "id": tc["id"], "name": tc["name"], "content": out})
            if tt.result:
                return tt.result
    audit.log("agent_stalled", invoice=tt.key, step=MAX_STEPS)
    return None
