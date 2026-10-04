"""Upload to YouTube, Instagram and TikTok via their official free APIs."""
import os
import time

import requests

from . import config


# ---------------- YouTube ----------------
def _yt_tags(tags):
    """YouTube allows ~500 characters of tags in total."""
    out, total = [], 0
    for t in dict.fromkeys(t.lstrip("#").strip() for t in tags if t):
        cost = len(t) + (2 if " " in t else 0) + 1  # YouTube counts quotes on multi-word tags + comma
        if total + cost > 495:
            break
        out.append(t)
        total += cost
    return out



def yt_service():
    """YouTube client for the owner's channel (refresh token from tools/get_youtube_token.py)."""
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
    # scopes=None: refresh with whatever the user granted (upload, plus force-ssl if they re-ran the token script)
    creds = Credentials(None, refresh_token=config.YT_REFRESH_TOKEN, client_id=config.YT_CLIENT_ID,
                        client_secret=config.YT_CLIENT_SECRET, token_uri="https://oauth2.googleapis.com/token")
    return build("youtube", "v3", credentials=creds, cache_discovery=False)


def add_to_playlist(yt, vid, name):
    """Series playlists ("What To Do If...") keep Shorts viewers binging the next video. ~51-101 quota units."""
    if not name:
        return "playlist skipped"
    found, page = None, None
    while not found:
        r = yt.playlists().list(part="snippet", mine=True, maxResults=50, pageToken=page).execute()
        found = next((p["id"] for p in r.get("items", []) if p["snippet"]["title"] == name), None)
        page = r.get("nextPageToken")
        if not page:
            break
    if not found:
        found = yt.playlists().insert(part="snippet,status", body={
            "snippet": {"title": name, "description": f"{config.CHANNEL_NAME}: {name} - animated in under a minute.",
                        "defaultLanguage": config.LANGUAGE},
            "status": {"privacyStatus": "public"}}).execute()["id"]
    yt.playlistItems().insert(part="snippet", body={"snippet": {
        "playlistId": found, "resourceId": {"kind": "youtube#video", "videoId": vid}}}).execute()
    return "playlist ✅"


def youtube(path, title, description, tags, category="24", thumb=None, srt=None, comment=None, publish_at=None,
            playlist=None):
    if not (config.YT_CLIENT_ID and config.YT_CLIENT_SECRET and config.YT_REFRESH_TOKEN):
        return None, "skipped (not configured)"
    from googleapiclient.errors import HttpError
    from googleapiclient.http import MediaFileUpload

    yt = yt_service()
    body = {
        "snippet": {"title": title[:100], "description": description[:4900],
                    "tags": _yt_tags(tags), "categoryId": str(category or "24"),
                    "defaultLanguage": config.LANGUAGE, "defaultAudioLanguage": config.LANGUAGE},
        "status": {"privacyStatus": config.YT_PRIVACY, "selfDeclaredMadeForKids": False,
                   "containsSyntheticMedia": True},  # YouTube's altered/synthetic content disclosure
    }
    scheduled = bool(publish_at and config.YT_PRIVACY == "public")
    if scheduled:  # YouTube makes it public by itself at publishAt (must be uploaded as private)
        body["status"]["privacyStatus"] = "private"
        body["status"]["publishAt"] = publish_at
    req = yt.videos().insert(part="snippet,status", body=body,
                             media_body=MediaFileUpload(path, mimetype="video/mp4", resumable=True))
    resp = None
    while resp is None:
        _, resp = req.next_chunk()
    vid = resp["id"]
    notes = ["scheduled" if scheduled else resp["status"].get("privacyStatus", "")]

    def why(e):
        msg = str(getattr(e, "reason", "") or e)
        if "permission" in msg.lower() or "verify" in msg.lower() or "forbidden" in msg.lower():
            return "needs a verified channel (youtube.com/verify)"
        if "insufficient" in msg.lower() or "scope" in msg.lower():
            return "needs re-login with the token script"
        return msg[:80]

    if thumb and os.path.exists(thumb):
        try:
            yt.thumbnails().set(videoId=vid, media_body=MediaFileUpload(thumb, mimetype="image/jpeg")).execute()
            notes.append("thumbnail ✅")
        except HttpError as e:
            notes.append(f"thumbnail ⚠️ {why(e)}")
    if srt and os.path.exists(srt):
        try:
            yt.captions().insert(part="snippet", sync=False, body={"snippet": {
                "videoId": vid, "language": config.LANGUAGE, "name": "Subtitles", "isDraft": False}},
                media_body=MediaFileUpload(srt, mimetype="application/octet-stream")).execute()
            notes.append("subtitles ✅")
        except HttpError as e:
            notes.append(f"subtitles ⚠️ {why(e)}")
    if comment:
        try:
            yt.commentThreads().insert(part="snippet", body={"snippet": {"videoId": vid, "topLevelComment": {
                "snippet": {"textOriginal": comment[:500]}}}}).execute()
            notes.append("comment ✅")
        except HttpError as e:
            notes.append(f"comment ⚠️ {why(e)}")
    if playlist:
        try:
            notes.append(add_to_playlist(yt, vid, playlist))
        except HttpError as e:
            notes.append(f"playlist ⚠️ {why(e)}")
    return f"https://youtube.com/shorts/{vid}", " · ".join(notes)


# ---------------- Instagram Reels ----------------
def instagram(path, caption):
    if not (config.IG_USER_ID and config.IG_ACCESS_TOKEN):
        return None, "skipped (not configured)"
    g = f"https://{config.IG_GRAPH_HOST}/{config.IG_API_VERSION}"
    tok = config.IG_ACCESS_TOKEN
    r = requests.post(f"{g}/{config.IG_USER_ID}/media", timeout=60, data={
        "media_type": "REELS", "upload_type": "resumable", "caption": caption[:2150],
        "share_to_feed": "true", "access_token": tok}).json()
    if "id" not in r:
        raise RuntimeError(f"IG container failed: {r}")
    cid = r["id"]
    with open(path, "rb") as f:
        up = requests.post(f"https://rupload.facebook.com/ig-api-upload/{config.IG_API_VERSION}/{cid}",
                           headers={"Authorization": f"OAuth {tok}", "offset": "0",
                                    "file_size": str(os.path.getsize(path))}, data=f, timeout=600)
    if up.status_code >= 300:
        raise RuntimeError(f"IG upload failed: {up.text}")
    for _ in range(60):
        s = requests.get(f"{g}/{cid}", params={"fields": "status_code,status", "access_token": tok}, timeout=30).json()
        if s.get("status_code") == "FINISHED":
            break
        if s.get("status_code") == "ERROR":
            raise RuntimeError(f"IG processing error: {s}")
        time.sleep(10)
    pub = requests.post(f"{g}/{config.IG_USER_ID}/media_publish", timeout=60,
                        data={"creation_id": cid, "access_token": tok}).json()
    if "id" not in pub:
        raise RuntimeError(f"IG publish failed: {pub}")
    link = requests.get(f"{g}/{pub['id']}", params={"fields": "permalink", "access_token": tok}, timeout=30).json()
    return link.get("permalink", f"media id {pub['id']}"), "published"


# ---------------- Facebook Page Reels ----------------
def facebook(path, caption, title=""):
    if not (config.FB_PAGE_ID and config.FB_PAGE_TOKEN):
        return None, "skipped (not configured)"
    g = f"https://graph.facebook.com/{config.IG_API_VERSION}"
    tok = config.FB_PAGE_TOKEN
    r = requests.post(f"{g}/{config.FB_PAGE_ID}/video_reels", timeout=60,
                      data={"upload_phase": "start", "access_token": tok}).json()
    if "video_id" not in r:
        raise RuntimeError(f"FB start failed: {r}")
    vid = r["video_id"]
    with open(path, "rb") as f:
        up = requests.post(r.get("upload_url") or f"https://rupload.facebook.com/video-upload/{config.IG_API_VERSION}/{vid}",
                           headers={"Authorization": f"OAuth {tok}", "offset": "0",
                                    "file_size": str(os.path.getsize(path))}, data=f, timeout=600)
    if up.status_code >= 300:
        raise RuntimeError(f"FB upload failed: {up.text[:200]}")
    fin = requests.post(f"{g}/{config.FB_PAGE_ID}/video_reels", timeout=60, data={
        "upload_phase": "finish", "video_id": vid, "video_state": "PUBLISHED",
        "title": title[:255], "description": caption[:2200], "access_token": tok}).json()
    if not fin.get("success"):
        raise RuntimeError(f"FB publish failed: {fin}")
    state = "processing"
    for _ in range(30):
        s = requests.get(f"{g}/{vid}", params={"fields": "status", "access_token": tok}, timeout=30).json()
        st = (s.get("status") or {})
        state = st.get("video_status", state)
        if state in ("ready", "error") or (st.get("publishing_phase") or {}).get("status") == "complete":
            break
        time.sleep(10)
    if state == "error":
        raise RuntimeError(f"FB processing error: {s}")
    return f"https://www.facebook.com/reel/{vid}", "published"


# ---------------- Captions per platform ----------------
def social_caption(title, description, hashtags, platform):
    """Short caption: title, the hook paragraph, credits/disclosure (required by the footage licenses), hashtags."""
    body, _, credits = description.partition("— Credits & disclosure —")
    first = next((p.strip() for p in body.split("\n\n") if p.strip() and not p.strip().startswith("#")), "")
    tags = [h if h.startswith("#") else f"#{h}" for h in hashtags]
    if platform == "instagram":
        tags = tags[:config.INSTAGRAM_HASHTAGS]
    elif platform == "tiktok":
        tags = (tags + ["#fyp"])[:5]
    else:
        tags = tags[:3]
    credit_lines = [l.strip() for l in credits.strip().splitlines() if l.strip()]
    limit = 2150
    tail = "\n\nCredits & AI disclosure:\n" + "\n".join(credit_lines) if credit_lines else ""
    tag_line = "\n\n" + " ".join(tags)
    room = limit - len(title) - len(tail) - len(tag_line) - 4
    if len(first) > room:
        first = first[:max(room - 1, 0)].rstrip() + "…"
    return f"{title}\n\n{first}{tail}{tag_line}"[:limit]


# ---------------- TikTok ----------------
def _tiktok_token():
    if config.TIKTOK_REFRESH_TOKEN and config.TIKTOK_CLIENT_KEY and config.TIKTOK_CLIENT_SECRET:
        r = requests.post("https://open.tiktokapis.com/v2/oauth/token/", timeout=30, data={
            "client_key": config.TIKTOK_CLIENT_KEY, "client_secret": config.TIKTOK_CLIENT_SECRET,
            "grant_type": "refresh_token", "refresh_token": config.TIKTOK_REFRESH_TOKEN}).json()
        if r.get("access_token"):
            return r["access_token"]
        print("TikTok token refresh failed:", r)
    return config.TIKTOK_ACCESS_TOKEN


def _tiktok_put(url, path, size):
    with open(path, "rb") as f:
        up = requests.put(url, data=f, timeout=600, headers={
            "Content-Type": "video/mp4", "Content-Length": str(size),
            "Content-Range": f"bytes 0-{size - 1}/{size}"})
    if up.status_code >= 300:
        raise RuntimeError(f"TikTok upload failed: {up.status_code} {up.text[:200]}")


def tiktok(path, caption):
    token = _tiktok_token()
    if not token:
        return None, "skipped (not configured)"
    size = os.path.getsize(path)
    hdr = {"Authorization": f"Bearer {token}", "Content-Type": "application/json; charset=UTF-8"}
    source = {"source": "FILE_UPLOAD", "video_size": size, "chunk_size": size, "total_chunk_count": 1}
    if config.TIKTOK_MODE != "direct":  # draft: lands in the TikTok app inbox, you finish + post it there
        r = requests.post("https://open.tiktokapis.com/v2/post/publish/inbox/video/init/", headers=hdr,
                          json={"source_info": source}, timeout=60).json()
        if r.get("error", {}).get("code") not in (None, "ok"):
            raise RuntimeError(f"TikTok draft init failed: {r}")
        _tiktok_put(r["data"]["upload_url"], path, size)
        return None, "draft sent to your TikTok inbox"
    post_info = {"title": caption[:2200], "privacy_level": config.TIKTOK_PRIVACY,
                 "disable_comment": False, "disable_duet": False, "disable_stitch": False,
                 "is_aigc": True}  # TikTok "AI-generated content" label
    body = {"post_info": post_info, "source_info": source}
    r = requests.post("https://open.tiktokapis.com/v2/post/publish/video/init/", headers=hdr, json=body, timeout=60).json()
    if r.get("error", {}).get("code") not in (None, "ok") and "is_aigc" in str(r):
        post_info.pop("is_aigc")
        r = requests.post("https://open.tiktokapis.com/v2/post/publish/video/init/", headers=hdr, json=body, timeout=60).json()
    if r.get("error", {}).get("code") not in (None, "ok"):
        raise RuntimeError(f"TikTok init failed: {r}")
    data = r["data"]
    _tiktok_put(data["upload_url"], path, size)
    status = "processing"
    for _ in range(30):
        s = requests.post("https://open.tiktokapis.com/v2/post/publish/status/fetch/", headers=hdr,
                          json={"publish_id": data["publish_id"]}, timeout=30).json()
        status = s.get("data", {}).get("status", status)
        if status in ("PUBLISH_COMPLETE", "FAILED"):
            break
        time.sleep(10)
    if status == "FAILED":
        raise RuntimeError(f"TikTok publish failed: {s}")
    return "https://www.tiktok.com/ (check your profile)", f"{status}, privacy={config.TIKTOK_PRIVACY}"


def publish_all(path, title, description, hashtags, tags=(), category="24", thumb=None, srt=None, comment=None,
                publish_at=None, playlist=None):
    cap = {p: social_caption(title, description, hashtags, p) for p in ("instagram", "facebook", "tiktok")}
    results = {}
    for name, fn in (("YouTube", lambda: youtube(path, title, description, list(tags) or [h.lstrip("#") for h in hashtags], category, thumb, srt, comment, publish_at, playlist)),
                     ("Instagram", lambda: instagram(path, cap["instagram"])),
                     ("Facebook", lambda: facebook(path, cap["facebook"], title)),
                     ("TikTok", lambda: tiktok(path, cap["tiktok"]))):
        try:
            results[name] = fn()
        except Exception as e:  # noqa: BLE001
            results[name] = (None, f"FAILED: {str(e)[:300]}")
    return results
