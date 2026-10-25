"""Company knowledge: markdown docs chunked by heading/paragraph, keyword-ranked retrieval."""
import os
import re

from . import config

KDIR = os.path.join(config.COMPANY_DIR, "knowledge")


def _chunks():
    out = []
    for fn in sorted(os.listdir(KDIR)):
        text = open(os.path.join(KDIR, fn)).read()
        for part in re.split(r"\n(?=#{1,3} )", text):
            if part.strip():
                out.append((fn, part.strip()))
    return out


def index():
    return [fn for fn in sorted(os.listdir(KDIR))]


def read_all():
    return "\n\n".join(f"=== {fn} ===\n{open(os.path.join(KDIR, fn)).read()}" for fn in index())


def search(query, k=3):
    words = set(re.findall(r"[a-z0-9]+", query.lower())) - {"the", "a", "of", "to", "for", "and", "is", "in"}
    scored = []
    for fn, c in _chunks():
        toks = re.findall(r"[a-z0-9]+", c.lower())
        score = sum(toks.count(w) for w in words)
        if score:
            scored.append((score, fn, c))
    scored.sort(reverse=True)
    return [f"[{fn}]\n{c}" for _, fn, c in scored[:k]] or ["No matching knowledge found."]
