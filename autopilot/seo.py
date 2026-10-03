"""YouTube tag optimizer (free): real search phrases from YouTube autocomplete,
ranked the way tag-score tools (vidIQ / TubeBuddy) reward:
  - the primary keyword first, and tags that also appear in the title / description
  - phrases people actually type on YouTube (autocomplete = real search demand)
  - specific long-tail + broader tags, no duplicates, ~450-490 of the 500 allowed characters
  - every tag must stay relevant (shares a word with the title/description/keyword) - no misleading tags
"""
import json
import re

import requests

from . import config

STOP = {"the", "a", "an", "and", "or", "of", "to", "in", "on", "for", "is", "are", "you", "your", "this", "that",
        "with", "how", "why", "what", "can", "do", "does", "it", "its", "my", "be", "at", "by", "from", "these"}


# generic words that may appear in a tag without being in the title (they don't change what it's about)
MODIFIERS = {"quiz", "questions", "answers", "trivia", "facts", "fact", "hard", "easy", "for", "adults", "game",
             "challenge", "test", "explained", "shorts", "short", "top", "best", "funny", "story", "stories", "tips",
             "hacks", "hack", "ideas", "amazing", "interesting", "weird", "cool", "fun", "ranking", "ranked", "list",
             "5", "10", "things", "you", "didn't", "know", "most", "ever", "world", "why", "how", "what"}


def _norm(w):
    return w[:-1] if len(w) > 3 and w.endswith("s") and not w.endswith("ss") else w  # planets -> planet


MODIFIERS = {_norm(m) for m in MODIFIERS}


def _words(text):
    return [_norm(w) for w in re.findall(r"[a-z0-9']+", (text or "").lower()) if w not in STOP and len(w) > 1]


def autocomplete(q):
    try:
        r = requests.get("https://suggestqueries.google.com/complete/search", timeout=10, params={
            "client": "firefox", "ds": "yt", "q": q, "hl": config.LANGUAGE, "gl": config.REGION})
        return [s for s in json.loads(r.text)[1] if isinstance(s, str)]
    except Exception as e:  # noqa: BLE001
        print("autocomplete failed:", str(e)[:80])
        return []


def _ai_select(pkg, candidates):
    """Let the AI keep only accurate tags (no brands, people, other games/shows, unrelated topics)."""
    from . import llm
    prompt = f"""You are a YouTube SEO expert. Pick the tags for this Short from REAL YouTube search suggestions.
Video title: {pkg.get('title')}
Main keyword: {pkg.get('primary_keyword')}
Description: {pkg.get('description')}

Candidate search phrases:
{chr(10).join('- ' + c for c in candidates)}

Choose 15-25 phrases that accurately describe THIS video (a viewer searching it would be happy to find this video).
Exclude: brand names, real people, other games/shows/movies, misleading or unrelated phrases, "for kids" phrases.
Order: most specific and most searched first. Return JSON {{"tags": ["..."]}} using phrases exactly as given."""
    picked = llm.ask_json(prompt, temperature=0.0).get("tags", [])
    allowed = set(candidates)
    return [t.lower().strip() for t in picked if t and t.lower().strip() in allowed]


def build_tags(pkg, limit_chars=490):
    title = re.sub(r"[^\w\s']", " ", pkg.get("title", ""))
    primary = (pkg.get("primary_keyword") or " ".join(_words(title)[:3])).lower().strip()
    desc = pkg.get("description", "")
    ai_tags = [t.lower().strip() for t in pkg.get("tags", []) if t]
    context = set(_words(title)) | set(_words(desc)) | set(_words(primary)) | {w for t in ai_tags for w in _words(t)}

    seeds = list(dict.fromkeys([primary, " ".join(_words(title)[:4])] + ai_tags[:5]))
    seeds += [f"{primary} {c}" for c in "abcdefghw"]  # widen: "funny cats a...", "funny cats w(hen)..."
    suggested = set()
    for seed in seeds:
        if seed.strip():
            suggested.update(s.lower().strip() for s in autocomplete(seed))

    # loose pre-filter: must share a real topic word with the video
    pool = [t for t in dict.fromkeys([primary] + ai_tags + sorted(suggested))
            if _words(t) and len(t) <= 60 and len(_words(t)) <= 6 and (set(_words(t)) - MODIFIERS) & context]
    try:
        chosen = set(_ai_select(pkg, pool[:120])) | {primary} | set(ai_tags)
    except Exception as e:  # noqa: BLE001
        print("AI tag selection failed, using strict filter:", str(e)[:100])
        chosen = {t for t in pool if not ((set(_words(t)) - MODIFIERS) - context)}

    title_l, desc_l = title.lower(), desc.lower()
    scored = []
    for tag in pool:
        if tag not in chosen:
            continue
        tw = _words(tag)
        overlap = len(set(tw) & context)
        score = overlap * 2
        score += 4 if tag in title_l else 0
        score += 2 if tag in desc_l else 0
        score += 3 if tag in suggested else 0  # real search phrase
        score += 1 if 2 <= len(tw) <= 4 else 0  # long-tail sweet spot
        score += 10 if tag == primary else 0
        scored.append((score, tag))
    scored.sort(key=lambda x: (-x[0], len(x[1])))

    out, total, seen = [], 0, set()
    for _, tag in scored:
        key = " ".join(sorted(_words(tag)))
        if key in seen:  # near-duplicate ("space quiz" vs "quiz space")
            continue
        cost = len(tag) + (2 if " " in tag else 0) + 1  # YouTube counts quotes around multi-word tags + comma
        if total + cost > limit_chars:
            continue
        out.append(tag)
        seen.add(key)
        total += cost
    print(f"SEO tags ({total} chars, {len(suggested)} suggestions seen): {out}")
    return out or ai_tags
