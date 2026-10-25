"""Model providers behind one interface. Local Ollama for the prototype; Anthropic API optional.

Internal message format (provider-neutral):
  {"role": "system"|"user", "content": str}
  {"role": "assistant", "content": str, "tool_calls": [{"id","name","args"}]}
  {"role": "tool", "id": str, "name": str, "content": str}
Tool spec: {"name","description","parameters": <json schema>}
"""
import json
import os
import re
import urllib.request
import uuid

from . import config


def _post(url, body, headers=None, timeout=900):
    req = urllib.request.Request(url, json.dumps(body).encode(),
                                 {"Content-Type": "application/json", **(headers or {})})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def extract_json(text):
    text = text.strip()
    try:
        return json.loads(text)
    except ValueError:
        pass
    m = re.search(r"\{.*\}", text, re.S)
    if m:
        return json.loads(m.group(0))
    raise ValueError("no JSON in model output: " + text[:200])


class Ollama:
    name = "ollama"

    def __init__(self, model=None):
        self.model = model or config.OLLAMA_MODEL

    def chat(self, messages, tools=None, json_mode=False):
        msgs = []
        for m in messages:
            if m["role"] == "assistant" and m.get("tool_calls"):
                msgs.append({"role": "assistant", "content": m.get("content", ""),
                             "tool_calls": [{"function": {"name": t["name"], "arguments": t["args"]}}
                                            for t in m["tool_calls"]]})
            elif m["role"] == "tool":
                msgs.append({"role": "tool", "content": m["content"], "tool_name": m["name"]})
            else:
                msgs.append({"role": m["role"], "content": m["content"]})
        body = {"model": self.model, "messages": msgs, "stream": False,
                "options": {"temperature": 0.1, "num_ctx": 16384}}
        if tools:
            body["tools"] = [{"type": "function", "function": t} for t in tools]
        if json_mode:
            body["format"] = "json"
        out = _post(config.OLLAMA_HOST + "/api/chat", body)["message"]
        calls = [{"id": uuid.uuid4().hex[:8], "name": c["function"]["name"],
                  "args": c["function"].get("arguments") or {}} for c in out.get("tool_calls") or []]
        return {"content": out.get("content", ""), "tool_calls": calls}


class Anthropic:
    name = "anthropic"

    def __init__(self, model=None):
        self.model = model or config.ANTHROPIC_MODEL
        self.key = os.environ.get("ANTHROPIC_API_KEY")
        if not self.key:
            raise RuntimeError("ANTHROPIC_API_KEY is not set")

    def chat(self, messages, tools=None, json_mode=False):
        system = "\n\n".join(m["content"] for m in messages if m["role"] == "system")
        if json_mode:
            system += "\n\nRespond with a single JSON object and nothing else."
        msgs = []
        for m in messages:
            if m["role"] == "system":
                continue
            if m["role"] == "assistant":
                blocks = [{"type": "text", "text": m["content"]}] if m.get("content") else []
                blocks += [{"type": "tool_use", "id": t["id"], "name": t["name"], "input": t["args"]}
                           for t in m.get("tool_calls", [])]
                msgs.append({"role": "assistant", "content": blocks})
            elif m["role"] == "tool":
                block = {"type": "tool_result", "tool_use_id": m["id"], "content": m["content"]}
                if msgs and msgs[-1]["role"] == "user" and isinstance(msgs[-1]["content"], list):
                    msgs[-1]["content"].append(block)
                else:
                    msgs.append({"role": "user", "content": [block]})
            else:
                msgs.append({"role": "user", "content": m["content"]})
        body = {"model": self.model, "max_tokens": 2048, "system": system, "messages": msgs}
        if tools:
            body["tools"] = [{"name": t["name"], "description": t["description"], "input_schema": t["parameters"]}
                             for t in tools]
        out = _post("https://api.anthropic.com/v1/messages", body,
                    {"x-api-key": self.key, "anthropic-version": "2023-06-01"})
        text = "".join(b["text"] for b in out["content"] if b["type"] == "text")
        calls = [{"id": b["id"], "name": b["name"], "args": b["input"]} for b in out["content"] if b["type"] == "tool_use"]
        return {"content": text, "tool_calls": calls}


def make_llm(provider):
    return {"ollama": Ollama, "anthropic": Anthropic}[provider]()
