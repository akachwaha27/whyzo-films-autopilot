"""Permanent archive for the dashboard / Excel sync on your PC.

state.json is trimmed to stay small (last 7 idea lists, last 30 videos). This module copies
everything into archive/ and never deletes it:
  archive/videos.json         one record per video: content, links, status, YouTube stats, latest comments
  archive/ideas.json          every daily idea list, with which ideas you picked
  archive/stats_history.json  daily channel totals (views, likes, comments) for trend charts
"""
import json
import os
import re

from . import config, state

FILES = ("videos", "ideas", "stats_history")


def _path(name):
    return os.path.join(config.LIBRARY_DIR, f"{name}.json")


def load(name):
    try:
        with open(_path(name)) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _save(name, data):
    os.makedirs(config.LIBRARY_DIR, exist_ok=True)
    tmp = _path(name) + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, indent=1, ensure_ascii=False, sort_keys=True)
    os.replace(tmp, _path(name))


def youtube_id(link):
    m = re.search(r"(?:shorts/|v=|youtu\.be/)([\w-]{11})", link or "")
    return m.group(1) if m else None


def _video_record(vid, v, old):
    from . import writer
    pkg = v.get("package") or {}
    topic = v.get("topic") or {}
    results = v.get("results") or {}
    rec = dict(old)  # keep stats/comments gathered earlier
    desc = v.get("description_full")
    if not desc and pkg:
        try:
            desc = writer.build_description(pkg, v.get("credits", []), human_reviewed=v.get("approved_by") == "you")
        except Exception:  # noqa: BLE001
            desc = pkg.get("description", "")
    rec.update({
        "id": vid,
        "date": vid[:10],
        "status": v.get("status"),
        "format": pkg.get("format") or topic.get("format", ""),
        "title": pkg.get("title") or topic.get("title", ""),
        "idea_title": topic.get("title", ""),
        "angle": topic.get("angle", ""),
        "trend_source": topic.get("trend_source", ""),
        "virality_score": topic.get("virality_score"),
        "description": desc or "",
        "script": pkg.get("script", ""),
        "hook_text": pkg.get("hook_text", ""),
        "thumbnail_text": pkg.get("thumbnail_text", ""),
        "primary_keyword": pkg.get("primary_keyword", ""),
        "hashtags": pkg.get("hashtags", []),
        "tags": pkg.get("tags", []),
        "pinned_comment": pkg.get("pinned_comment", ""),
        "key_facts": pkg.get("key_facts", []),
        "voice": pkg.get("voice", ""),
        "category": pkg.get("category", ""),
        "credits": v.get("credits", []),
        "subtitles_srt": v.get("srt", ""),
        "approved_by": v.get("approved_by", ""),
        "redos": v.get("redos", 0),
        "uploaded_at": v.get("uploaded_at", ""),
        "scheduled_for": v.get("slot", ""),
        "updated": v.get("updated", ""),
        "file": v.get("file"),
        "thumb": v.get("thumb"),
        "platforms": {k: {"link": r[0], "status": r[1]} for k, r in results.items() if isinstance(r, (list, tuple))},
    })
    yt = (results.get("YouTube") or [None])[0]
    if youtube_id(yt):
        rec["youtube_id"] = youtube_id(yt)
    return rec


def record(st):
    """Copy everything from state into the permanent library (cheap; called on every save)."""
    videos = load("videos")
    changed = False
    for vid, v in st.get("videos", {}).items():
        rec = _video_record(vid, v, videos.get(vid, {}))
        if rec != videos.get(vid):
            videos[vid] = rec
            changed = True
    if changed:
        _save("videos", videos)

    ideas = load("ideas")
    by_title = {v.get("idea_title") or v.get("title"): k for k, v in videos.items()}
    changed = False
    for day, b in st.get("batches", {}).items():
        sel = set(b.get("selected") or [])
        rows = []
        for i, t in enumerate(b.get("topics", [])):
            rows.append({
                "rank": i + 1, "title": t.get("title", ""), "format": t.get("format", ""),
                "angle": t.get("angle", ""), "why": t.get("why", ""), "trend_source": t.get("trend_source", ""),
                "virality_score": t.get("virality_score"), "picked": i in sel,
                "video_id": by_title.get(t.get("title")),
            })
        entry = {"date": day[:10], "run": day, "sent_at": b.get("sent_at", ""), "status": b.get("status", ""), "ideas": rows}
        if ideas.get(day) != entry:
            ideas[day] = entry
            changed = True
    if changed:
        _save("ideas", ideas)


def refresh_stats(force=False):
    """Pull views / likes / comment counts and latest comments for every uploaded video (~1 quota unit each)."""
    meta = load("stats_history")
    last = meta.get("_last_run")
    if not force and last and (state.now() - state.parse(last)).total_seconds() < config.STATS_EVERY_HOURS * 3600:
        return False
    if not (config.YT_CLIENT_ID and config.YT_CLIENT_SECRET and config.YT_REFRESH_TOKEN):
        return False
    from . import publish
    videos = load("videos")
    ids = {r["youtube_id"]: k for k, r in videos.items() if r.get("youtube_id")}
    if not ids:
        return False
    yt = publish.yt_service()
    keys = list(ids)
    for i in range(0, len(keys), 50):
        resp = yt.videos().list(part="statistics,status,snippet", id=",".join(keys[i:i + 50])).execute()
        seen = set()
        for item in resp.get("items", []):
            rec = videos[ids[item["id"]]]
            s = item.get("statistics", {})
            rec["youtube_stats"] = {
                "views": int(s.get("viewCount", 0)), "likes": int(s.get("likeCount", 0)),
                "comments": int(s.get("commentCount", 0)),
                "privacy": item.get("status", {}).get("privacyStatus", ""),
                "published_at": item.get("snippet", {}).get("publishedAt", ""),
                "title": item.get("snippet", {}).get("title", ""),  # your current title, if you renamed it in Studio
                "checked_at": state.iso(),
            }
            seen.add(item["id"])
        for missing in set(keys[i:i + 50]) - seen:
            videos[ids[missing]].setdefault("youtube_stats", {})["privacy"] = "removed"
    # latest comments for videos from the last 30 days
    for yid, k in ids.items():
        rec = videos[k]
        if (rec.get("youtube_stats") or {}).get("privacy") == "removed":
            continue
        if rec.get("date", "") < _days_ago(30):
            continue
        try:
            resp = yt.commentThreads().list(part="snippet", videoId=yid, maxResults=20, order="time",
                                            textFormat="plainText").execute()
        except Exception as e:  # noqa: BLE001  comments off, private video, or missing scope
            rec["comments_note"] = str(e)[:120]
            continue
        rec["latest_comments"] = [{
            "author": c["snippet"]["topLevelComment"]["snippet"].get("authorDisplayName", ""),
            "text": c["snippet"]["topLevelComment"]["snippet"].get("textDisplay", ""),
            "likes": c["snippet"]["topLevelComment"]["snippet"].get("likeCount", 0),
            "published": c["snippet"]["topLevelComment"]["snippet"].get("publishedAt", ""),
            "replies": c["snippet"].get("totalReplyCount", 0),
        } for c in resp.get("items", [])]
        rec.pop("comments_note", None)
    _save("videos", videos)
    tot = {"views": 0, "likes": 0, "comments": 0, "videos": 0}
    for r in videos.values():
        s = r.get("youtube_stats") or {}
        if s and s.get("privacy") != "removed":
            tot["videos"] += 1
            for f in ("views", "likes", "comments"):
                tot[f] += s.get(f, 0)
    meta[state.now().date().isoformat()] = tot
    meta["_last_run"] = state.iso()
    _save("stats_history", meta)
    return True


def _days_ago(n):
    from datetime import timedelta
    return (state.now() - timedelta(days=n)).date().isoformat()
