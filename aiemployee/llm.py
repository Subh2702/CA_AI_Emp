"""Model providers behind one interface. Local Ollama for the prototype; Hugging Face Inference API for hosted use.

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


class HuggingFace:
    """Hugging Face Inference Providers: OpenAI-compatible chat completions with tool calling."""
    name = "huggingface"

    def __init__(self, model=None):
        self.model = model or config.HF_MODEL
        self.key = os.environ.get("HF_TOKEN")
        if not self.key:
            raise RuntimeError("HF_TOKEN is not set")

    def chat(self, messages, tools=None, json_mode=False):
        msgs = []
        for m in messages:
            if m["role"] == "assistant" and m.get("tool_calls"):
                msgs.append({"role": "assistant", "content": m.get("content") or None,
                             "tool_calls": [{"id": t["id"], "type": "function",
                                             "function": {"name": t["name"], "arguments": json.dumps(t["args"])}}
                                            for t in m["tool_calls"]]})
            elif m["role"] == "tool":
                msgs.append({"role": "tool", "tool_call_id": m["id"], "content": m["content"]})
            else:
                msgs.append({"role": m["role"], "content": m["content"]})
        if json_mode:
            msgs.append({"role": "user", "content": "Respond with a single JSON object and nothing else."})
        body = {"model": self.model, "messages": msgs, "temperature": 0.1, "max_tokens": 2048}
        if tools:
            body["tools"] = [{"type": "function", "function": t} for t in tools]
            body["tool_choice"] = "auto"
        out = _post(config.HF_BASE_URL + "/chat/completions", body,
                    {"Authorization": "Bearer " + self.key})["choices"][0]["message"]
        calls = []
        for c in out.get("tool_calls") or []:
            args = c["function"].get("arguments") or {}
            if isinstance(args, str):
                try:
                    args = json.loads(args or "{}")
                except ValueError:
                    args = {}
            calls.append({"id": c.get("id") or uuid.uuid4().hex[:8], "name": c["function"]["name"], "args": args})
        return {"content": out.get("content") or "", "tool_calls": calls}


def make_llm(provider):
    return {"ollama": Ollama, "huggingface": HuggingFace}[provider]()
