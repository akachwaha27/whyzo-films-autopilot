"""Free AI text generation with automatic fallback across providers.

Order (each is skipped if not configured):
  1. Google Gemini      - GEMINI_API_KEY      (Flash -> Flash-Lite -> Gemma)
  2. Groq               - GROQ_API_KEY        (optional, free)
  3. Cerebras           - CEREBRAS_API_KEY    (optional, free)
  4. Mistral            - MISTRAL_API_KEY     (optional, free "Experiment" plan)
  5. OpenRouter :free   - OPENROUTER_API_KEY  (optional, free; small daily cap, so later in line)
  6. Cloudflare AI      - CF_ACCOUNT_ID + CF_API_TOKEN (optional, free)

Model names are discovered from each provider's model list at runtime, so
retired models don't break anything. Every call returns parsed JSON.
"""
import json
import os
import re
import time

import requests

from . import config

GEMINI = "https://generativelanguage.googleapis.com/v1beta"
SKIP = ("image", "tts", "live", "audio", "embedding", "thinking", "exp", "preview", "8b",
        "whisper", "guard", "vision", "coder", "embed", "rerank", "distil", "moderation", "ocr",
        "codestral", "devstral", "transcribe", "voxtral", "pixtral", "saba")
JSON_HINT = "\n\nRespond with ONLY valid JSON. No markdown, no explanations."
_plan = None  # list of (provider_name, model, call_fn)


# ---------------- helpers ----------------
def _version(name):
    nums = re.findall(r"\d+(?:\.\d+)?", name)
    return float(nums[0]) if nums else 0.0


def _size(name):
    sizes = [float(x) for x in re.findall(r"(\d+(?:\.\d+)?)b\b", name.lower())]
    return max(sizes or [0])


def _parse(text):
    """Pull the first JSON object out of a model reply, ignoring chatter around it."""
    text = re.sub(r"<think>.*?</think>", "", text or "", flags=re.S).strip()  # reasoning models
    text = re.sub(r"^```(?:json)?|```$", "", text).strip()
    if not text:
        raise ValueError("empty reply")
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        if start < 0:
            raise ValueError(f"no JSON in reply: {text[:80]!r}")
        obj, _ = json.JSONDecoder().raw_decode(text[start:])  # stops at end of first object
        return obj


def _ok_name(n):
    return not any(s in n.lower() for s in SKIP)


# ---------------- providers ----------------
def _gkey():
    """Header auth works for both classic (AIza...) and newer (AQ....) Gemini keys, and keeps keys out of URLs/logs."""
    return {"x-goog-api-key": config.GEMINI_API_KEY}


def _gemini_models():
    r = requests.get(f"{GEMINI}/models", params={"pageSize": 200}, headers=_gkey(), timeout=30)
    r.raise_for_status()
    names = [m["name"].split("/", 1)[1] for m in r.json().get("models", [])
             if "generateContent" in m.get("supportedGenerationMethods", []) and _ok_name(m["name"])]
    order = lambda xs: sorted(xs, key=lambda n: (_version(n), -len(n)), reverse=True)  # noqa: E731
    flash = order([n for n in names if n.startswith("gemini") and "flash" in n and "lite" not in n])[:3]
    lite = order([n for n in names if n.startswith("gemini") and "flash" in n and "lite" in n])[:2]
    gemma = sorted([n for n in names if n.startswith("gemma") and "it" in n.split("-")],
                   key=lambda n: (_version(n), _size(n)), reverse=True)[:1]
    return flash + lite + gemma


def _gemini_call(model, prompt, temperature):
    gen = {"temperature": temperature}
    if model.startswith("gemini"):
        gen["responseMimeType"] = "application/json"
    r = requests.post(f"{GEMINI}/models/{model}:generateContent", headers=_gkey(),
                      json={"contents": [{"role": "user", "parts": [{"text": prompt}]}], "generationConfig": gen},
                      timeout=180)
    if r.status_code >= 400:
        raise RuntimeError(f"HTTP {r.status_code}: {r.text[:160]}")
    return _parse(r.json()["candidates"][0]["content"]["parts"][0]["text"])


def _openai_call(url, key, model, prompt, temperature, extra_headers=None):
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json",
               "Accept": "application/json", **(extra_headers or {})}
    r = requests.post(url, headers=headers, timeout=180, json={
        "model": model, "temperature": temperature, "stream": False,
        "messages": [{"role": "user", "content": prompt + JSON_HINT}]})
    if r.status_code >= 400:
        raise RuntimeError(f"HTTP {r.status_code}: {r.text[:160]}")
    try:
        data = r.json()
    except ValueError:
        raise RuntimeError(f"non-JSON response ({r.headers.get('content-type')}): {r.text[:120]!r}") from None
    if "choices" not in data or not data["choices"]:
        raise RuntimeError(f"no answer: {str(data.get('error', data))[:140]}")
    msg = data["choices"][0].get("message") or {}
    content = msg.get("content")
    if isinstance(content, list):  # some APIs return content parts
        content = "".join(p.get("text", "") for p in content if isinstance(p, dict))
    if not content:
        raise RuntimeError(f"empty reply (finish_reason={data['choices'][0].get('finish_reason')})")
    return _parse(content)


def _groq_models():
    r = requests.get("https://api.groq.com/openai/v1/models", timeout=30,
                     headers={"Authorization": f"Bearer {os.getenv('GROQ_API_KEY')}"})
    r.raise_for_status()
    ids = [m["id"] for m in r.json().get("data", []) if m.get("active", True) and _ok_name(m["id"])]
    return sorted(ids, key=_size, reverse=True)[:2]


def _rank(n):
    """Bigger / higher-tier models first."""
    n = n.lower()
    tier = 300 if "large" in n else 200 if "medium" in n else 100 if "small" in n else 0
    return _size(n) + tier + (5 if "latest" in n else 0)


def _compat_models(base, key_env):
    r = requests.get(f"{base}/models", timeout=30, headers={"Authorization": f"Bearer {os.getenv(key_env)}"})
    r.raise_for_status()
    ids = [m["id"] for m in r.json().get("data", []) if _ok_name(m["id"])]
    return sorted(ids, key=_rank, reverse=True)[:2]


def _openrouter_models():
    r = requests.get("https://openrouter.ai/api/v1/models", timeout=30)
    r.raise_for_status()
    ids = [m["id"] for m in r.json().get("data", []) if m["id"].endswith(":free") and _ok_name(m["id"])]
    return sorted(ids, key=_size, reverse=True)[:2]


def _cloudflare_models():
    r = requests.get(f"https://api.cloudflare.com/client/v4/accounts/{config.CF_ACCOUNT_ID}/ai/models/search",
                     params={"task": "Text Generation", "per_page": 100}, timeout=30,
                     headers={"Authorization": f"Bearer {config.CF_API_TOKEN}"})
    r.raise_for_status()
    ids = [m["name"] for m in r.json().get("result", []) if "instruct" in m["name"] and _ok_name(m["name"])]
    return sorted(ids, key=_size, reverse=True)[:1]


def _build_plan():
    plan = []

    def add(provider, lister, caller):
        try:
            for m in lister():
                plan.append((provider, m, caller))
        except Exception as e:  # noqa: BLE001
            print(f"{provider}: could not list models ({str(e)[:100]})")

    if config.GEMINI_API_KEY:
        pinned = [config.GEMINI_MODEL] if config.GEMINI_MODEL else []

        def gem_list():
            try:
                found = _gemini_models()
            except Exception as e:  # noqa: BLE001
                print("Gemini model list failed, using defaults:", str(e)[:100])
                found = ["gemini-2.5-flash", "gemini-2.5-flash-lite"]
            return pinned + [m for m in found if m not in pinned]
        add("Gemini", gem_list, _gemini_call)
    if os.getenv("GROQ_API_KEY"):
        add("Groq", _groq_models, lambda m, p, t: _openai_call(
            "https://api.groq.com/openai/v1/chat/completions", os.getenv("GROQ_API_KEY"), m, p, t))
    for name, key_env, base in (("Cerebras", "CEREBRAS_API_KEY", "https://api.cerebras.ai/v1"),
                                ("Mistral", "MISTRAL_API_KEY", "https://api.mistral.ai/v1")):
        if os.getenv(key_env):
            add(name, lambda b=base, k=key_env: _compat_models(b, k),
                lambda m, p, t, b=base, k=key_env: _openai_call(f"{b}/chat/completions", os.getenv(k), m, p, t))
    if os.getenv("OPENROUTER_API_KEY"):
        add("OpenRouter", _openrouter_models, lambda m, p, t: _openai_call(
            "https://openrouter.ai/api/v1/chat/completions", os.getenv("OPENROUTER_API_KEY"), m, p, t,
            {"X-Title": "Whyzo Films"}))
    if config.CF_ACCOUNT_ID and config.CF_API_TOKEN:
        add("Cloudflare", _cloudflare_models, lambda m, p, t: _openai_call(
            f"https://api.cloudflare.com/client/v4/accounts/{config.CF_ACCOUNT_ID}/ai/v1/chat/completions",
            config.CF_API_TOKEN, m, p, t))
    if not plan:
        raise RuntimeError("No AI provider configured. Add GEMINI_API_KEY (or GROQ_API_KEY / OPENROUTER_API_KEY).")
    print("AI fallback order:", [f"{p}:{m}" for p, m, _ in plan])
    return plan


def health_check():
    """Ping every configured provider/model once. Returns list of (provider, model, ok, detail)."""
    out = []
    for provider, model, call in _build_plan():
        t0 = time.time()
        try:
            ans = call(model, 'Return this exact JSON: {"ok": true}', 0)
            out.append((provider, model, bool(ans.get("ok")), f"{time.time() - t0:.1f}s"))
        except Exception as e:  # noqa: BLE001
            out.append((provider, model, False, str(e)[:90]))
    return out


def ask_json(prompt, temperature=0.7, passes=2):
    """Try every provider/model once per pass; the first good JSON answer wins."""
    global _plan
    if _plan is None:
        _plan = _build_plan()
    last = None
    for p in range(passes):
        for i, (provider, model, call) in enumerate(list(_plan)):
            try:
                result = call(model, prompt, temperature)
                if i:  # start with whatever worked for the rest of this run
                    _plan.insert(0, _plan.pop(i))
                    print(f"Now using {provider}:{model}")
                return result
            except Exception as e:  # noqa: BLE001
                last = f"{provider}:{model} -> {str(e)[:120]}"
                print("AI attempt failed:", last)
                time.sleep(4)
        if p < passes - 1:
            print("All AI providers busy; waiting 60s before another pass")
            time.sleep(60)
    raise RuntimeError(f"All free AI providers are busy right now. Last error: {last}")
