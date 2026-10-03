"""Voiceover, visuals and final render for Whyzo Films.

Voice:    one consistent narrator (Microsoft Edge neural TTS, free); Google gTTS as backup.
Visuals:  3D-style AI stills (fal.ai FLUX, or free Cloudflare FLUX), the key shots animated with
          fal.ai image-to-video (ANIMATE_SHOTS per video), the rest get slow camera moves.
          Stock footage (Pexels/Pixabay/NASA/Commons) is only a fallback if AI images fail.
Render:   FFmpeg, 1080x1920, burned-in captions, soft whoosh on scene changes, light music.
"""
import asyncio
import base64
import html
import json
import math
import os
import random
import re
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor

import requests

from . import config

W, H, FPS = config.WIDTH, config.HEIGHT, config.FPS
UA = {"User-Agent": "WhyzoFilms/1.0 (https://github.com/akachwaha27/whyzo-films-autopilot)"}


def run(cmd):
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode != 0:
        raise RuntimeError(f"Command failed: {' '.join(cmd[:6])}...\n{p.stderr[-1500:]}")
    return p.stdout


def duration(path):
    return float(run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                      "-of", "default=nw=1:nk=1", path]).strip())


# =========================== Voice ===========================
VOICE_POOL = {
    "en": ["en-US-AndrewMultilingualNeural", "en-US-AvaMultilingualNeural", "en-US-BrianMultilingualNeural",
           "en-US-EmmaMultilingualNeural", "en-US-ChristopherNeural", "en-US-JennyNeural", "en-US-GuyNeural",
           "en-US-AriaNeural", "en-GB-RyanNeural", "en-GB-SoniaNeural", "en-AU-WilliamNeural",
           "en-AU-NatashaNeural", "en-CA-LiamNeural", "en-IE-ConnorNeural"],
}


def voice_pool():
    if config.VOICES:  # user override: comma-separated list
        return [v.strip() for v in config.VOICES.split(",") if v.strip()]
    lang = config.LANGUAGE.split("-")[0]
    pool = VOICE_POOL.get(lang)
    try:  # keep only voices that exist right now (Microsoft adds/retires voices)
        import edge_tts
        live = {v["ShortName"] for v in asyncio.run(edge_tts.list_voices())}
        if pool:
            pool = [v for v in pool if v in live] or pool
        else:  # other languages: any neural voice for that language
            pool = sorted(v for v in live if v.lower().startswith(lang + "-"))[:12]
    except Exception as e:  # noqa: BLE001
        print("Could not list voices:", str(e)[:100])
    return pool or [config.VOICE]


def pick_voice(recent):
    pool = voice_pool()
    fresh = [v for v in pool if v not in recent[-2:]] or pool
    return random.choice(fresh)


async def _edge(text, mp3, words, voice, rate, pitch):
    import edge_tts
    com = edge_tts.Communicate(text, voice, rate=rate, pitch=pitch, boundary="WordBoundary")
    with open(mp3, "wb") as f:
        async for chunk in com.stream():
            if chunk["type"] == "audio":
                f.write(chunk["data"])
            elif chunk["type"] == "WordBoundary":
                words.append({"start": chunk["offset"] / 1e7,
                              "end": (chunk["offset"] + chunk["duration"]) / 1e7, "word": chunk["text"]})


def _estimate_words(text, total):
    """No timing data (gTTS): spread words over the audio by length."""
    ws = text.split()
    weights = [len(w) + 2 for w in ws]
    t, out = 0.15, []
    span = max(total - 0.3, 0.5)
    for w, k in zip(ws, weights):
        d = span * k / sum(weights)
        out.append({"start": t, "end": t + d * 0.9, "word": w})
        t += d
    return out


def voiceover(text, out_dir, voice):
    mp3 = os.path.join(out_dir, "voice.mp3")
    rate, pitch = "+6%", "+0Hz"  # same narrator sound on every video
    for v in (voice, config.VOICE):
        try:
            words = []
            asyncio.run(_edge(text, mp3, words, v, rate, pitch))
            if os.path.getsize(mp3) > 1000 and words:
                return mp3, words, f"AI-generated voice (Microsoft Edge neural TTS, {v})"
        except Exception as e:  # noqa: BLE001
            print(f"edge-tts voice {v} failed: {str(e)[:120]}")
    from gtts import gTTS  # backup engine
    gTTS(text, lang=config.LANGUAGE.split("-")[0]).save(mp3)
    return mp3, _estimate_words(text, duration(mp3)), "AI-generated voice (Google Text-to-Speech)"


# =========================== Captions & overlays ===========================
def _ts(t):
    h, rem = divmod(max(t, 0), 3600)
    m, s = divmod(rem, 60)
    return f"{int(h)}:{int(m):02d}:{s:05.2f}"


def _clean(t):
    return re.sub(r"[{}\\]", "", str(t))


def subtitles(words, scenes, bounds, hook_text, path, group=3):
    head = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {W}
PlayResY: {H}
WrapStyle: 0

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,DejaVu Sans,86,&H00FFFFFF,&H00FFFFFF,&H00000000,&H64000000,1,0,0,0,100,100,0,0,1,6,3,2,80,80,620,1
Style: Rank,DejaVu Sans,210,&H0000D7FF,&H0000D7FF,&H00000000,&H80000000,1,0,0,0,100,100,0,0,1,9,4,8,60,60,200,1
Style: Label,DejaVu Sans,74,&H00FFFFFF,&H00FFFFFF,&H00000000,&HA0000000,1,0,0,0,100,100,0,0,3,10,0,8,90,90,450,1
Style: Title,DejaVu Sans,80,&H0000D7FF,&H0000D7FF,&H00000000,&HA0000000,1,0,0,0,100,100,0,0,3,12,0,8,80,80,260,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lines = []
    for i in range(0, len(words), group):
        chunk = words[i:i + group]
        end = words[i + group]["start"] if i + group < len(words) else chunk[-1]["end"] + 0.3
        text = _clean(" ".join(w["word"] for w in chunk).upper())
        lines.append(f"Dialogue: 0,{_ts(chunk[0]['start'])},{_ts(end)},Default,,0,0,0,,{text}")
    for idx, (s, (a, b)) in enumerate(zip(scenes, bounds)):
        badge, label = _clean(s.get("badge", "")), _clean(s.get("label", ""))
        if badge:
            size = r"\fs210" if len(badge) <= 3 else r"\fs130"
            pop = r"{\fad(120,80)" + size + r"\fscx135\fscy135\t(0,220,\fscx100\fscy100)}"
            lines.append(f"Dialogue: 1,{_ts(a)},{_ts(b)},Rank,,0,0,0,,{pop}{badge}")
        if label and not (idx == 0 and hook_text and not badge):  # don't stack on the hook
            margin = "" if badge else r"\pos(540,300)"
            lines.append(f"Dialogue: 1,{_ts(a)},{_ts(b)},Label,,0,0,0,,{{\\fad(150,80){margin}}}{label.upper()}")
        if idx == 0 and hook_text and not badge:
            lines.append(f"Dialogue: 1,{_ts(0)},{_ts(b)},Title,,0,0,0,,"
                         r"{\fad(100,120)\fscx120\fscy120\t(0,200,\fscx100\fscy100)}" + _clean(hook_text).upper())
    with open(path, "w", encoding="utf-8") as f:
        f.write(head + "\n".join(lines) + "\n")
    return path


def _srt_ts(t):
    t = max(t, 0)
    h, rem = divmod(t, 3600)
    m, sec = divmod(rem, 60)
    return f"{int(h):02d}:{int(m):02d}:{int(sec):02d},{int(round((sec % 1) * 1000)) % 1000:03d}"


def srt(words, path, max_words=7, max_chars=42):
    """Readable closed-caption track (separate from the burned-in captions)."""
    cues, cur = [], []
    for w in words:
        cur.append(w)
        text = " ".join(x["word"] for x in cur)
        if len(cur) >= max_words or len(text) >= max_chars or w["word"].rstrip().endswith((".", "?", "!")):
            cues.append(cur)
            cur = []
    if cur:
        cues.append(cur)
    out = []
    for i, c in enumerate(cues, 1):
        end = cues[i][0]["start"] if i < len(cues) else c[-1]["end"] + 0.4
        out.append(f"{i}\n{_srt_ts(c[0]['start'])} --> {_srt_ts(end)}\n{' '.join(x['word'] for x in c)}\n")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(out))
    return path


def scene_bounds(scenes, words, total):
    """Start/end time of each scene, aligned to the actual spoken words."""
    counts = [max(len(s["text"].split()), 1) for s in scenes]
    tot, cum, starts = sum(counts), 0, []
    for c in counts:
        idx = min(int(round(cum / tot * len(words))), len(words) - 1) if words else 0
        starts.append(0.0 if cum == 0 or not words else words[idx]["start"])
        cum += c
    ends = starts[1:] + [total]
    return [(a, max(b, a + 0.8)) for a, b in zip(starts, ends)]


# =========================== Footage sources ===========================
def _download(url, path, headers=None, max_mb=120):
    with requests.get(url, stream=True, timeout=180, headers=headers) as r:
        r.raise_for_status()
        size = 0
        with open(path, "wb") as f:
            for c in r.iter_content(1 << 20):
                size += len(c)
                if size > max_mb << 20:
                    raise RuntimeError("file too large")
                f.write(c)
    return path


def _pexels(path, params):
    r = requests.get(f"https://api.pexels.com/{path}", params=params, timeout=30,
                     headers={"Authorization": config.PEXELS_API_KEY})
    r.raise_for_status()
    return r.json()


def pexels_video(query, base, used):
    for v in _pexels("videos/search", {"query": query, "orientation": "portrait", "size": "medium", "per_page": 10}).get("videos", []):
        files = [f for f in v["video_files"] if f.get("height") and f["height"] >= 1280 and f["width"] < f["height"]]
        if f"pex{v['id']}" in used or not files:
            continue
        used.add(f"pex{v['id']}")
        _download(min(files, key=lambda f: f["height"])["link"], base + ".mp4")
        return {"kind": "video", "path": base + ".mp4", "credit": f'{v["user"]["name"]} (Pexels) {v["url"]}'}


def pexels_photo(query, base, used):
    for p in _pexels("v1/search", {"query": query, "orientation": "portrait", "per_page": 10}).get("photos", []):
        if f"pexp{p['id']}" in used:
            continue
        used.add(f"pexp{p['id']}")
        _download(p["src"]["large2x"], base + ".jpg")
        return {"kind": "image", "path": base + ".jpg", "credit": f'{p["photographer"]} (Pexels) {p["url"]}'}


def _pixabay(path, params):
    r = requests.get(f"https://pixabay.com/api/{path}", timeout=30,
                     params={"key": config.PIXABAY_API_KEY, "safesearch": "true", "per_page": 20, **params})
    r.raise_for_status()
    return r.json()


def pixabay_video(query, base, used):
    hits = _pixabay("videos/", {"q": query[:100]}).get("hits", [])
    hits.sort(key=lambda h: h["videos"].get("large", {}).get("height", 0) < h["videos"].get("large", {}).get("width", 1))
    for v in hits:
        files = [f for f in (v["videos"].get(s) for s in ("medium", "large", "small")) if f and f.get("url")]
        if f"pxb{v['id']}" in used or not files:
            continue
        used.add(f"pxb{v['id']}")
        _download(files[0]["url"], base + ".mp4")
        return {"kind": "video", "path": base + ".mp4", "credit": f'{v["user"]} (Pixabay) {v["pageURL"]}'}


def pixabay_photo(query, base, used):
    for p in _pixabay("", {"q": query[:100], "image_type": "photo", "orientation": "vertical"}).get("hits", []):
        if f"pxbp{p['id']}" in used:
            continue
        used.add(f"pxbp{p['id']}")
        _download(p["largeImageURL"], base + ".jpg")
        return {"kind": "image", "path": base + ".jpg", "credit": f'{p["user"]} (Pixabay) {p["pageURL"]}'}


SPACE_WORDS = {"space", "planet", "rocket", "earth", "moon", "mars", "sun", "star", "stars", "galaxy", "nebula",
               "astronaut", "satellite", "orbit", "launch", "comet", "asteroid", "aurora", "telescope", "universe",
               "solar", "eclipse", "jupiter", "saturn", "venus", "spacecraft", "iss", "cosmos", "meteor", "hubble"}


def _nasa(query, base, used, media_type):
    if not SPACE_WORDS & set(re.findall(r"[a-z]+", query.lower())):
        return None  # NASA search returns loose matches; only use it for space/science scenes
    r = requests.get("https://images-api.nasa.gov/search", timeout=30,
                     params={"q": query, "media_type": media_type, "page_size": 15})
    r.raise_for_status()
    for item in r.json().get("collection", {}).get("items", []):
        d = item["data"][0]
        if f"nasa{d['nasa_id']}" in used:
            continue
        assets = requests.get(item["href"], timeout=30).json()
        prefs = ("~mobile.mp4", "~small.mp4", "~medium.mp4") if media_type == "video" else ("~large.jpg", "~medium.jpg", "~orig.jpg")
        url = next((a for p in prefs for a in assets if a.endswith(p)), None)
        if not url:
            continue
        used.add(f"nasa{d['nasa_id']}")
        ext = ".mp4" if media_type == "video" else ".jpg"
        _download(url.replace("http://", "https://"), base + ext)
        return {"kind": "video" if media_type == "video" else "image", "path": base + ext,
                "credit": f"NASA{' / ' + d['center'] if d.get('center') else ''}: \"{d.get('title', '')[:60]}\" (public domain)"}


def nasa_video(q, base, used):
    return _nasa(q, base, used, "video")


def nasa_photo(q, base, used):
    return _nasa(q, base, used, "image")


OK_LICENSE = re.compile(r"^(cc0|public domain|pd|cc by \d(\.\d)?|cc-by-\d(\.\d)?)", re.I)  # no share-alike


def _commons(query, base, used, kind):
    ftype = "video" if kind == "video" else "bitmap"
    stop = {"with", "from", "that", "this", "into", "over", "under", "about", "close", "view", "shot", "background"}
    keywords = [w for w in re.findall(r"[a-z]{4,}", query.lower()) if w not in stop]
    if not keywords:
        return None
    r = requests.get("https://commons.wikimedia.org/w/api.php", headers=UA, timeout=30, params={
        "action": "query", "format": "json", "generator": "search", "gsrnamespace": 6, "gsrlimit": 12,
        "gsrsearch": f"{query} filetype:{ftype}", "prop": "imageinfo",
        "iiprop": "url|size|mime|extmetadata", "iiurlwidth": 1600})
    r.raise_for_status()
    for page in (r.json().get("query", {}).get("pages", {}) or {}).values():
        info = (page.get("imageinfo") or [{}])[0]
        meta = info.get("extmetadata", {})
        lic = meta.get("LicenseShortName", {}).get("value", "")
        if f"wm{page['pageid']}" in used or not OK_LICENSE.match(lic.strip()):
            continue
        name = page.get("title", "").lower()
        if not any(w in name for w in keywords):  # Commons search is loose: require a real match
            continue
        if kind == "video" and (info.get("size", 0) > 80 << 20 or info.get("duration", 99) < 3):
            continue
        if kind == "image" and info.get("width", 0) < 800:
            continue
        url = info.get("url") if kind == "video" else info.get("thumburl") or info.get("url")
        ext = os.path.splitext(url.split("?")[0])[1] or (".webm" if kind == "video" else ".jpg")
        artist = html.unescape(re.sub(r"<[^>]+>", " ", meta.get("Artist", {}).get("value", "Unknown")))
        artist = re.sub(r"\s+", " ", artist).strip()
        if "all rights reserved" in artist.lower() or "copyright" in name:
            continue
        artist = (artist[:len(artist) // 2].strip() if artist[:len(artist) // 2] == artist[len(artist) // 2:].strip()
                  else artist)[:60] or "Unknown"
        used.add(f"wm{page['pageid']}")
        _download(url, base + ext, headers=UA)
        return {"kind": kind, "path": base + ext,
                "credit": f"{artist} / Wikimedia Commons ({lic}) {info.get('descriptionurl', '')}"}


def commons_video(q, base, used):
    return _commons(q, base, used, "video")


def commons_photo(q, base, used):
    return _commons(q, base, used, "image")


def styled(prompt):
    return f"{prompt}. {config.ART_STYLE}"


def _fal(model, payload, timeout=900):
    """Run a fal.ai model through its queue API and return the result JSON."""
    head = {"Authorization": f"Key {config.FAL_KEY}"}
    r = requests.post(f"https://queue.fal.run/{model}", headers=head, json=payload, timeout=60)
    r.raise_for_status()
    job = r.json()
    deadline = time.time() + timeout
    while time.time() < deadline:
        st = requests.get(job["status_url"], headers=head, timeout=30).json()
        status = st.get("status")
        if status == "COMPLETED":
            break
        if status not in ("IN_QUEUE", "IN_PROGRESS"):
            raise RuntimeError(f"fal {model}: {str(st)[:200]}")
        time.sleep(5)
    else:
        raise RuntimeError(f"fal {model} timed out")
    res = requests.get(job["response_url"], headers=head, timeout=60)
    res.raise_for_status()
    return res.json()


def fal_image(prompt, base):
    out = _fal(config.FAL_IMAGE_MODEL, {"prompt": styled(prompt), "image_size": {"width": 864, "height": 1536},
                                        "num_inference_steps": 4, "output_format": "jpeg"})
    url = out["images"][0]["url"]
    _download(url, base + ".jpg")
    return {"kind": "image", "path": base + ".jpg", "url": url, "credit": "AI 3D image (FLUX via fal.ai)"}


def cf_image(prompt, base):
    url = (f"https://api.cloudflare.com/client/v4/accounts/{config.CF_ACCOUNT_ID}"
           "/ai/run/@cf/black-forest-labs/flux-1-schnell")
    r = requests.post(url, headers={"Authorization": f"Bearer {config.CF_API_TOKEN}"}, timeout=120,
                      json={"prompt": styled(prompt), "steps": 8})
    r.raise_for_status()
    with open(base + ".png", "wb") as f:
        f.write(base64.b64decode(r.json()["result"]["image"]))
    return {"kind": "image", "path": base + ".png", "credit": "AI 3D image (FLUX.1-schnell via Cloudflare Workers AI)"}


def ai_image(prompt, base):
    if config.FAL_KEY:
        try:
            return fal_image(prompt, base)
        except Exception as e:  # noqa: BLE001
            print("fal image failed, trying Cloudflare:", str(e)[:150])
    if config.CF_ACCOUNT_ID and config.CF_API_TOKEN:
        return cf_image(prompt, base)
    return None


VIDEO_PRESETS = {
    "wan": ("fal-ai/wan/v2.2-a14b/image-to-video",
            {"resolution": "720p", "aspect_ratio": "9:16", "num_frames": 81, "frames_per_second": 16,
             "negative_prompt": "text, watermark, logo, blurry, distorted face, extra limbs, gore, blood"}),
    "kling": ("fal-ai/kling-video/v2.1/standard/image-to-video", {"duration": "5"}),
}


def animate(vis, motion, base):
    """Turn a still into a ~5 second moving shot (fal.ai image-to-video)."""
    model, extra = VIDEO_PRESETS.get(config.FAL_VIDEO_MODEL, (config.FAL_VIDEO_MODEL, {}))
    image_url = vis.get("url")
    if not image_url:
        mime = "image/png" if vis["path"].endswith(".png") else "image/jpeg"
        with open(vis["path"], "rb") as f:
            image_url = f"data:{mime};base64," + base64.b64encode(f.read()).decode()
    out = _fal(model, {"prompt": f"{motion}. Smooth 3D animation, consistent characters, no text", "image_url": image_url, **extra})
    _download(out["video"]["url"], base + ".mp4")
    return {"kind": "video", "path": base + ".mp4", "credit": f"AI animation ({model.split('/')[1]} via fal.ai)"}


def source_plan():
    """Per-video shuffled order of stock providers, so videos don't all look alike."""
    providers = []
    if config.PEXELS_API_KEY:
        providers.append((pexels_video, pexels_photo))
    if config.PIXABAY_API_KEY:
        providers.append((pixabay_video, pixabay_photo))
    random.shuffle(providers)
    # NASA only answers for space scenes; Commons last because its matches are looser
    return [(nasa_video, nasa_photo)] + providers + [(commons_video, commons_photo)]


def get_visual(scene, i, out_dir, used, plan):
    base = os.path.join(out_dir, f"s{i}")
    q = scene.get("stock_query") or scene.get("label") or "abstract background"
    has_ai = bool(config.FAL_KEY or (config.CF_ACCOUNT_ID and config.CF_API_TOKEN))
    use_ai = has_ai and (config.VISUALS == "ai" or (config.VISUALS == "mixed" and i % 2 == 1))
    attempts = [lambda: ai_image(scene.get("image_prompt", q), base)] if use_ai else []
    for vid, pic in plan:  # video first, then photo, from each provider in this video's order
        attempts += [lambda f=vid: f(q, base, used), lambda f=pic: f(q, base, used)]
    short = q.split()[0] if q.split() else q
    for vid, pic in plan[1:]:  # broader one-word search as a second chance
        attempts.append(lambda f=vid: f(short, base, used))
    if has_ai and not use_ai:
        attempts.append(lambda: ai_image(scene.get("image_prompt", q), base))
    for fn in attempts:
        try:
            res = fn()
            if res:
                return res
        except Exception as e:  # noqa: BLE001
            print(f"  visual attempt failed for scene {i}: {str(e)[:120]}")
    return {"kind": "gradient", "path": None, "credit": None}


# =========================== Render ===========================
FILL = f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},setsar=1"
PALETTES = [("0x0b1d51", "0x6a1b9a", "0x00897b"), ("0x1a237e", "0xc2185b", "0xff8f00"),
            ("0x004d40", "0x1565c0", "0x7b1fa2"), ("0x3e2723", "0xbf360c", "0xf9a825")]


def render_scene(vis, dur, out):
    common = ["-t", f"{dur:.3f}", "-r", str(FPS), "-an", "-c:v", "libx264", "-preset", "veryfast",
              "-crf", "22", "-pix_fmt", "yuv420p", out]
    if vis["kind"] == "video":
        vf = f"{FILL},fps={FPS}"
        try:  # gently slow a short AI clip to fill its scene instead of visibly looping it
            clip = duration(vis["path"])
            if clip < dur <= clip * 1.6:
                vf = f"setpts={dur / clip:.4f}*PTS,{vf}"
        except Exception:  # noqa: BLE001
            pass
        run(["ffmpeg", "-y", "-stream_loop", "-1", "-i", vis["path"], "-vf", vf] + common)
    elif vis["kind"] == "image":
        frames = int(dur * FPS) + 1
        z = random.choice(["min(1+0.0009*on,1.15)", "max(1.15-0.0009*on,1)"])
        vf = (f"scale={W * 2}:{H * 2}:force_original_aspect_ratio=increase,crop={W * 2}:{H * 2},"
              f"zoompan=z='{z}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={frames}:s={W}x{H}:fps={FPS},setsar=1")
        run(["ffmpeg", "-y", "-loop", "1", "-i", vis["path"], "-vf", vf] + common)
    else:  # animated gradient instead of a flat colour
        c0, c1, c2 = random.choice(PALETTES)
        run(["ffmpeg", "-y", "-f", "lavfi", "-i",
             f"gradients=s={W}x{H}:c0={c0}:c1={c1}:c2={c2}:n=3:speed=0.012:r={FPS}"] + common)
    return out


def pick_music():
    folder = "assets/music"
    tracks = [f for f in os.listdir(folder) if f.lower().endswith((".mp3", ".m4a", ".wav"))] if os.path.isdir(folder) else []
    return os.path.join(folder, random.choice(tracks)) if tracks else None


def pick_animated(scenes, bounds):
    """Which scenes get real motion: always the hook, then the longest of the rest, spread out."""
    n = min(config.ANIMATE_SHOTS, len(scenes)) if config.FAL_KEY else 0
    if n <= 0:
        return set()
    rest = sorted(range(1, len(scenes)), key=lambda i: bounds[i][1] - bounds[i][0], reverse=True)
    return {0, *rest[:n - 1]}


def whoosh_track(times, total, out_dir):
    """A quiet whoosh at every scene change (synthesized, so no licensing)."""
    times = [t for t in times if 0.3 < t < total - 0.3]
    if not times:
        return None
    one = os.path.join(out_dir, "whoosh.wav")
    run(["ffmpeg", "-y", "-f", "lavfi", "-i", "anoisesrc=d=0.5:c=pink:a=0.6:r=44100",
         "-af", "highpass=f=400,lowpass=f=2800,afade=t=in:d=0.22,afade=t=out:st=0.22:d=0.28", one])
    track = os.path.join(out_dir, "sfx.wav")
    split = f"[0:a]asplit={len(times)}" + "".join(f"[w{i}]" for i in range(len(times))) + ";"
    delays = "".join(f"[w{i}]adelay={max(int((t - 0.25) * 1000), 0)}:all=1[d{i}];" for i, t in enumerate(times))
    mixin = "".join(f"[d{i}]" for i in range(len(times)))
    run(["ffmpeg", "-y", "-i", one, "-filter_complex",
         f"{split}{delays}{mixin}amix=inputs={len(times)}:normalize=0,apad[out]", "-map", "[out]",
         "-t", f"{total:.2f}", track])
    return track


def make_video(pkg, out_dir, recent_voices=()):
    """Builds final.mp4. Sets pkg['voice']. Returns (path, credit_lines)."""
    os.makedirs(out_dir, exist_ok=True)
    voice = pick_voice(list(recent_voices))
    audio, words, voice_credit = voiceover(pkg["script"], out_dir, voice)
    pkg["voice"] = voice if "Edge" in voice_credit else "gTTS"
    total = duration(audio) + 0.6
    scenes = pkg["scenes"]
    bounds = scene_bounds(scenes, words, total)
    hook = pkg.get("hook_text") or ""
    ass = subtitles(words, scenes, bounds, hook, os.path.join(out_dir, "captions.ass"))

    used, credits, plan = set(), [], source_plan()
    animate_set = pick_animated(scenes, bounds)
    angles = ["", ", close-up detail shot", ", wide shot from a different angle"]
    shots = []  # (scene index, shot index, duration, visual)
    for i, (scene, (a, b)) in enumerate(zip(scenes, bounds)):
        dur = b - a
        n = 1 if i in animate_set or dur < 3.6 else min(3, math.ceil(dur / 3.2))  # a fresh shot roughly every 3s
        queries = scene.get("stock_queries") or [scene.get("stock_query", "")]
        for k in range(n):
            shot = dict(scene, stock_query=queries[k % len(queries)],
                        image_prompt=scene.get("image_prompt", "") + angles[k % len(angles)])
            shots.append([i, k, dur / n, get_visual(shot, f"{i}_{k}", out_dir, used, plan)])

    def _anim(item):
        i, k, _, vis = item
        try:
            return animate(vis, scenes[i].get("motion", ""), os.path.join(out_dir, f"anim{i}"))
        except Exception as e:  # noqa: BLE001
            print(f"  animation failed for scene {i} (using camera move instead): {str(e)[:150]}")
            return None

    todo = [it for it in shots if it[0] in animate_set and it[3]["kind"] == "image"]
    if todo and config.FAL_KEY:
        with ThreadPoolExecutor(max_workers=4) as pool:
            for it, res in zip(todo, pool.map(_anim, todo)):
                if res:
                    it[3] = res
    pkg["animated_shots"] = sum(1 for it in shots if it[3].get("credit", "") and "animation" in it[3]["credit"])

    parts, first_shot = [], {}  # scene index -> its first clean (caption-free) shot, used for the thumbnail
    for i, k, dur, vis in shots:
        if vis["credit"] and vis["credit"] not in credits:
            credits.append(vis["credit"])
        parts.append(render_scene(vis, dur, os.path.join(out_dir, f"part{i:02d}_{k}.mp4")))
        first_shot.setdefault(i, (parts[-1], vis["kind"]))

    concat = os.path.join(out_dir, "parts.txt")
    with open(concat, "w") as f:
        f.writelines(f"file '{os.path.abspath(p)}'\n" for p in parts)

    final = os.path.join(out_dir, "final.mp4")
    music = pick_music()
    sfx = whoosh_track([a for a, _ in bounds[1:]], total, out_dir) if config.SFX else None
    cmd = ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", concat, "-i", audio]
    mix, n_in = ["[1:a]"], 1
    pre = ""
    if music:
        cmd += ["-stream_loop", "-1", "-i", music]
        n_in += 1
        pre += f"[{n_in}:a]volume=0.09[m];"
        mix.append("[m]")
    if sfx:
        cmd += ["-i", sfx]
        n_in += 1
        pre += f"[{n_in}:a]volume=0.35[x];"
        mix.append("[x]")
    if len(mix) > 1:
        cmd += ["-filter_complex", f"{pre}{''.join(mix)}amix=inputs={len(mix)}:duration=first:dropout_transition=0:normalize=0[a]",
                "-map", "0:v", "-map", "[a]"]
    else:
        cmd += ["-map", "0:v", "-map", "1:a"]
    cmd += ["-vf", f"ass={ass}", "-c:v", "libx264", "-preset", "medium", "-crf", "21", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "160k", "-ar", "44100", "-t", f"{total:.2f}", "-movflags", "+faststart", final]
    run(cmd)

    srt(words, os.path.join(out_dir, "captions.srt"))
    try:
        from . import thumbnail
        top = next((i for i, sc in enumerate(scenes) if sc.get("badge") == "#1"), None)
        # prefer a real footage shot: the #1 reveal for rankings, else the first scene with real footage
        order = ([top] if top is not None else []) + [i for i in range(1, len(scenes))] + [0]
        pick = next((i for i in order if first_shot.get(i, (0, "gradient"))[1] != "gradient"), order[0])
        clip = first_shot[pick][0]
        thumbnail.make(clip, min(0.6, duration(clip) / 2), pkg.get("thumbnail_text") or pkg.get("hook_text")
                       or pkg["title"], os.path.join(out_dir, "thumbnail.jpg"), badge="#1" if top is not None else "",
                       accent_index=random.randrange(4))
    except Exception as e:  # noqa: BLE001
        print("Thumbnail failed:", str(e)[:150])

    stock = [c for c in credits if "(Pexels)" in c or "(Pixabay)" in c]
    other = [c for c in credits if c not in stock]
    credit_lines = [f"Voiceover: {voice_credit}."]
    if stock:
        credit_lines.append("Stock footage/photos (Pexels/Pixabay Content License): " + "; ".join(stock))
    credit_lines += other
    if music:
        credit_lines.append(f"Music: {os.path.basename(music)} (royalty-free, see assets/music/LICENSES.txt)")
    if sfx:
        credit_lines.append("Sound effects: generated by the channel.")
    with open(os.path.join(out_dir, "credits.json"), "w") as f:
        json.dump(credit_lines, f)
    return final, credit_lines
