"""Wikipedia evidence for the script's factual claims (free, no key).

For each claim in pkg["key_facts"] we run a Wikipedia full-text search and pull the intro of the
best-matching articles. The review step then checks the script against that text instead of relying
only on the model's memory. Any network failure just means "no evidence" - it never blocks a video.
"""
import re

import requests

from . import config

API = "https://{lang}.wikipedia.org/w/api.php"
UA = {"User-Agent": "WhyzoFilms/1.0 (https://github.com/akachwaha27/whyzo-films-autopilot)"}
MAX_FACTS = 8
PAGES_PER_FACT = 2
EXTRACT_CHARS = 1200
TOTAL_CHARS = 9000


def _lang():
    return (config.LANGUAGE or "en").split("-")[0].lower()


def _get(params):
    r = requests.get(API.format(lang=_lang()), headers=UA, timeout=20,
                     params={"format": "json", "formatversion": 2, **params})
    r.raise_for_status()
    return r.json()


def _query(fact):
    """Wikipedia search works best on short keyword strings, not full sentences."""
    words = re.findall(r"[\w'.,-]+", fact)
    return " ".join(words[:14])


def search(fact):
    hits = _get({"action": "query", "list": "search", "srsearch": _query(fact),
                 "srlimit": PAGES_PER_FACT, "srprop": ""})
    return [h["title"] for h in hits.get("query", {}).get("search", [])]


def extracts(titles):
    if not titles:
        return {}
    data = _get({"action": "query", "prop": "extracts|info", "inprop": "url", "exintro": 1,
                 "explaintext": 1, "exchars": EXTRACT_CHARS, "redirects": 1, "titles": "|".join(titles[:20])})
    out = {}
    for p in data.get("query", {}).get("pages", []):
        text = (p.get("extract") or "").strip()
        if text and not p.get("missing"):
            out[p["title"]] = {"text": re.sub(r"\s+", " ", text), "url": p.get("fullurl", "")}
    return out


def gather(pkg):
    """Returns {"evidence": str for the reviewer, "sources": [url, ...]}. Empty when nothing found."""
    facts = [str(f).strip() for f in (pkg.get("key_facts") or []) if str(f).strip()][:MAX_FACTS]
    if not facts or pkg.get("format") == "story":
        return {"evidence": "", "sources": []}
    titles = []
    for fact in facts:
        try:
            for t in search(fact):
                if t not in titles:
                    titles.append(t)
        except Exception as e:  # noqa: BLE001
            print("wikipedia search failed:", str(e)[:120])
    try:
        pages = extracts(titles)
    except Exception as e:  # noqa: BLE001
        print("wikipedia extract failed:", str(e)[:120])
        return {"evidence": "", "sources": []}
    blocks, used, sources = [], 0, []
    for t in titles:
        p = pages.get(t)
        if not p:
            continue
        block = f"[{t}] {p['text']}"
        if used + len(block) > TOTAL_CHARS:
            break
        blocks.append(block)
        sources.append(p["url"])
        used += len(block)
    print(f"fact-check: {len(facts)} claims -> {len(blocks)} Wikipedia articles")
    return {"evidence": "\n\n".join(blocks), "sources": sources}
