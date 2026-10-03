"""Entry point.

  python -m autopilot.main trends          # every 6 hours: find ideas, send them to Telegram
  python -m autopilot.main poll            # stay online a while: read replies, generate, publish, confirm
  python -m autopilot.main test [format]   # render one sample video and send it to Telegram (no publishing)
  python -m autopilot.main aicheck         # test every configured AI provider
"""
import html
import os
import random
import re
import sys
import time
import traceback
from datetime import timedelta

from . import config, library, llm, media, publish, schedule, state, storage, telegram, trends, writer

FMT_LETTERS = {"h": "howitworks", "w": "why", "i": "whatif", "s": "survival", "t": "truestory", "c": "creature", "k": "hack"}
RUNS = "abcd"  # four idea runs a day (UTC 00-06, 06-12, 12-18, 18-24)
MAX_REDOS = 5


def esc(s):
    return html.escape(str(s))


def today():
    return state.now().strftime("%Y-%m-%d")


def fmt_label(fmt):
    f = writer.FORMATS.get(fmt, writer.FORMATS[writer.fmt_of({"format": fmt or "why"})])
    return f"{f['emoji']} {f['name']}"


def num(vid):
    return vid.rsplit("-", 1)[-1]  # e.g. "b2" = run b, idea 2


def run_id():
    return f"{today()}-{RUNS[state.now().hour // 6]}"


# ---------------------------------------------------------------- trends
def cmd_trends(st):
    bid = run_id()
    tries = st.setdefault("trend_tries", {})
    tries[bid] = {"n": tries.get(bid, {}).get("n", 0) + 1, "at": state.iso()}
    for d in sorted(tries)[:-6]:
        tries.pop(d)
    for old, b in st["batches"].items():  # a new run closes the previous idea list
        if b["status"] == "waiting" and old != bid:
            auto_select(st, force=old)
    signals = trends.collect()
    topics = trends.pick_topics(signals, st.get("history", []))
    if not topics:
        telegram.send("⚠️ No safe ideas found this time. I'll try again in 6 hours.")
        return
    st["batches"][bid] = {"topics": topics, "sent_at": state.iso(), "selected": [], "status": "waiting"}
    lines = [f"🎬 <b>{esc(config.CHANNEL_NAME)}: next {len(topics)} ideas</b> (run {num(bid).upper()})\n"]
    for i, t in enumerate(topics, 1):
        lines.append(f"<b>{i}. {esc(t['title'])}</b>\n   {fmt_label(t.get('format'))} · ⭐{t.get('virality_score', '?')}/10\n"
                     f"   {esc(t['angle'])}\n   <i>Inspired by: {esc(t.get('trend_source', ''))}</i>\n")
    lines.append(
        "<b>How to reply</b>\n"
        "• Tap a number below, or type <code>1,3</code>\n"
        "• Change the format by adding a letter: <code>2h</code> ⚙️ how it works, <code>2w</code> 🤔 why, "
        "<code>2i</code> 🤯 what if, <code>2s</code> 🛟 survival, <code>2t</code> 📜 true story, "
        "<code>2c</code> 🦎 creature, <code>2k</code> 🛠️ hack\n"
        f"• No reply in {config.SELECT_TIMEOUT_HOURS * 60:g} min → I'll make the top {config.AUTO_PICK_COUNT}.")
    buttons = [[(f"🎬 {i}", f"pick:{bid}:{i - 1}") for i in range(1, len(topics) + 1)],
               [("⏭ Skip this run", f"skip:{bid}")]]
    telegram.send("\n".join(lines), buttons)


# ---------------------------------------------------------------- helpers
def videos_today(st):
    return sum(1 for k in st["videos"] if k.startswith(today()))


def queue_topic(st, bid, idx, by="you", fmt=None):
    batch = st["batches"].get(bid)
    if not batch or idx < 0 or idx >= len(batch["topics"]) or idx in batch["selected"]:
        return False
    if videos_today(st) >= config.MAX_VIDEOS_PER_DAY:
        telegram.send(f"Daily limit of {config.MAX_VIDEOS_PER_DAY} videos reached; skipping #{idx + 1}.")
        return False
    batch["selected"].append(idx)
    vid = f"{bid}{idx + 1}"
    topic = dict(batch["topics"][idx])
    if fmt:
        topic["format"] = fmt
    st["videos"][vid] = {"topic": topic, "status": "queued", "by": by, "updated": state.iso(), "redos": 0}
    telegram.send(f"✅ Queued video #{idx + 1} ({fmt_label(topic.get('format'))}): <b>{esc(topic['title'])}</b>\n"
                  "I'll send the preview in about 5-10 minutes.")
    return True


def latest_waiting(st):
    waiting = [b for b, v in st["batches"].items() if v["status"] == "waiting"]
    return max(waiting) if waiting else None


HELP = (
    "<b>Commands</b>\n"
    "• <code>1,3</code> pick from the latest ideas (add h/w/i/s/t/c/k to change format, e.g. <code>2s</code>)\n"
    "• <code>publish</code> (next peak time) · <code>publish now</code> · <code>skip</code> · <code>redo</code> · <code>voice</code>\n"
    "• <code>change make it funnier</code> rewrite a preview with your notes\n"
    "• <code>title Your New Title</code> change just the title\n"
    "• <code>info</code> see title, description, tags\n"
    "• Add the video number when several are waiting: <code>publish b2</code>, <code>change c1 shorter</code>\n"
    "• /now new ideas · /status recent videos · /help this list")


# ---------------------------------------------------------------- telegram input
CMD_RE = re.compile(r"^/?(publish|post|approve|yes|ok|skip|reject|no|discard|redo|regenerate|change|edit|"
                    r"voice|title|info|details)\b[\s:,-]*(.*)$", re.I | re.S)


def handle_updates(st, wait=0):
    ups = telegram.updates(st.get("tg_offset", 0), wait)
    for u in ups:
        st["tg_offset"] = u["update_id"] + 1
        cb = u.get("callback_query")
        msg = u.get("message")
        chat = (cb or {}).get("message", {}).get("chat", {}).get("id") if cb else (msg or {}).get("chat", {}).get("id")
        if str(chat) != str(config.TELEGRAM_CHAT_ID):
            continue  # ignore strangers
        try:
            if cb:
                handle_button(st, cb)
            elif msg and msg.get("text"):
                handle_text(st, msg)
        except Exception as e:  # noqa: BLE001
            traceback.print_exc()
            telegram.send(f"⚠️ Couldn't handle that: {esc(str(e)[:200])}")


def handle_button(st, cb):
    kind, *rest = cb["data"].split(":")
    telegram.answer_callback(cb["id"], "Got it")
    if kind == "pick":
        queue_topic(st, rest[0], int(rest[1]))
    elif kind == "skip" and rest[0] in st["batches"]:
        st["batches"][rest[0]]["status"] = "skipped"
        telegram.send("👍 Skipping this run.")
    elif rest and rest[0] in st["videos"]:
        action = {"ok": "publish", "no": "skip", "redo": "redo", "voice": "voice", "info": "info"}.get(kind)
        if action:
            act(st, rest[0], action, "")


def handle_text(st, msg):
    raw = msg["text"].strip()
    text = raw.lower()
    if text in ("/status", "status"):
        rows = [f"#{num(k)} {k[:10]}: {v['status']} – {esc(v['topic']['title'])}"
                for k, v in sorted(st["videos"].items())[-8:]]
        telegram.send("📋 <b>Recent videos</b>\n" + ("\n".join(rows) or "none yet"))
    elif text in ("/now", "/trends", "now"):
        telegram.send("🔎 Looking for fresh ideas...")
        cmd_trends(st)
    elif text in ("/help", "help", "/start", "?"):
        telegram.send(HELP)
    elif CMD_RE.match(raw):
        word, rest = CMD_RE.match(raw).groups()
        action = {"post": "publish", "approve": "publish", "yes": "publish", "ok": "publish",
                  "reject": "skip", "no": "skip", "discard": "skip", "regenerate": "redo", "edit": "change",
                  "details": "info"}.get(word.lower(), word.lower())
        m = re.match(r"^#?([a-d]?\d+|all)\b[\s:,-]*(.*)$", rest.strip(), re.I | re.S)
        which, arg = (m.group(1).lower(), m.group(2).strip()) if m else (None, rest.strip())
        targets = resolve(st, msg, which, action)
        for vid in targets:
            act(st, vid, action, arg)
    elif re.fullmatch(r"[\d,\s" + "".join(FMT_LETTERS) + "]+", text) and re.search(r"\d", text):
        bid = latest_waiting(st)
        if not bid:
            telegram.send("No open idea list right now (ideas arrive every 6 hours). Send /now to get fresh ideas.")
            return
        for n, f in re.findall(r"(\d+)\s*([" + "".join(FMT_LETTERS) + "]?)", text):
            queue_topic(st, bid, int(n) - 1, fmt=FMT_LETTERS.get(f))
    else:
        telegram.send("I didn't get that. " + HELP)


def resolve(st, msg, which, action):
    """Figure out which video a command is about."""
    waiting = [k for k, v in sorted(st["videos"].items()) if v["status"] == "awaiting_approval"]
    reply_id = (msg.get("reply_to_message") or {}).get("message_id")
    if reply_id:
        hit = [k for k, v in st["videos"].items() if reply_id in (v.get("tg_msg"), v.get("opts_msg"))]
        if hit:
            return hit
    if which == "all":
        if action in ("publish", "skip"):
            return waiting
        telegram.send(f"<code>{action} all</code> isn't supported; pick one video number.")
        return []
    if which:
        hit = [k for k in reversed(waiting) if num(k) == which] or \
              [k for k in sorted(st["videos"], reverse=True) if num(k) == which]
        if hit:
            return hit[:1]
        telegram.send(f"I can't find video #{which}. /status shows recent videos.")
        return []
    if len(waiting) == 1:
        return waiting
    if not waiting:
        telegram.send("Nothing is waiting for your review right now. /status shows recent videos.")
        return []
    nums = ", ".join(f"#{num(k)}" for k in waiting)
    telegram.send(f"{len(waiting)} videos are waiting ({nums}). Add the number, e.g. "
                  f"<code>{action} {num(waiting[-1])}</code>, or reply directly to the video.")
    return []


def act(st, vid, action, arg):
    v = st["videos"][vid]
    pkg = v.get("package", {})
    n = num(vid)
    if v["status"] != "awaiting_approval" and action != "info":
        telegram.send(f"Video #{n} is {v['status'].replace('_', ' ')}, so I can't {action} it now.")
        return
    if action == "publish":
        now_flag = arg.strip().lower().startswith("now")
        v.update(status="approved", approved_by="you", updated=state.iso(), publish_now=now_flag)
        when = "right now" if now_flag or not config.SCHEDULE_PUBLISH else "at the next peak time"
        telegram.send(f"👍 Uploading video #{n} ({when}): {esc(pkg.get('title', ''))}")
    elif action == "skip":
        v.update(status="rejected", updated=state.iso())
        telegram.send(f"🗑 Skipped video #{n}.")
    elif action in ("redo", "change", "voice"):
        if v.get("redos", 0) >= MAX_REDOS:
            telegram.send(f"Video #{n} has been remade {MAX_REDOS} times already. Publish or skip it, "
                          "or pick a new idea with /now.")
            return
        if action == "change" and not arg:
            telegram.send("Tell me what to change, e.g. <code>change make it funnier and shorter</code> "
                          "or <code>change turn it into a quiz</code>.")
            return
        v["redos"] = v.get("redos", 0) + 1
        if action == "voice":
            v["status"] = "revoice"
            telegram.send(f"🎙 Re-recording video #{n} with a different voice and fresh footage (~3 min)...")
        else:
            topic = v["topic"]
            topic.pop("feedback", None)
            if action == "change":
                topic["feedback"] = arg[:500]
                newfmt = next((f for f in writer.FORMATS if f in arg.lower()), None)
                if newfmt:
                    topic["format"] = newfmt
            v["status"] = "queued"
            what = f"with your notes: <i>{esc(arg[:200])}</i>" if action == "change" else "from scratch"
            telegram.send(f"🔁 Rewriting video #{n} {what} (~4 min)...")
        v["updated"] = state.iso()
    elif action == "title":
        if not arg:
            telegram.send("Send the new title after the word title, e.g. <code>title The Ocean's Weirdest Secret</code>")
            return
        pkg["title"] = arg[:95]
        v["updated"] = state.iso()
        telegram.send(f"🏷 Video #{n} title is now: <b>{esc(pkg['title'])}</b>\nReply <code>publish</code> when ready.")
    elif action == "info":
        if not pkg:
            telegram.send(f"Video #{n} is {v['status']} (no details yet).")
            return
        desc = writer.build_description(pkg, v.get("credits", []))
        telegram.send(f"ℹ️ <b>Video #{n}</b> · {fmt_label(pkg.get('format'))} · 🎙 {esc(pkg.get('voice', ''))}\n\n"
                      f"<b>Title:</b> {esc(pkg['title'])}\n<b>Main keyword:</b> {esc(pkg.get('primary_keyword', ''))}\n"
                      f"<b>Tags:</b> {esc(', '.join(pkg.get('tags', [])))}\n"
                      f"<b>Pinned comment:</b> {esc(pkg.get('pinned_comment', ''))}\n\n"
                      f"<b>Description:</b>\n{esc(desc)[:3000]}")


def auto_select(st, force=None):
    for bid, b in st["batches"].items():
        if b["status"] != "waiting" or (force and bid != force):
            continue
        age = state.now() - state.parse(b["sent_at"])
        if force or age >= timedelta(hours=config.SELECT_TIMEOUT_HOURS):
            if not b["selected"]:
                telegram.send(f"⏰ No reply, so I'm making the top {config.AUTO_PICK_COUNT} ideas.")
                for i in range(min(config.AUTO_PICK_COUNT, len(b["topics"]))):
                    queue_topic(st, bid, i, by="auto")
            b["status"] = "closed"


# ---------------------------------------------------------------- generate & publish
def render_and_preview(st, vid, pkg):
    v = st["videos"][vid]
    out = os.path.join(config.WORK_DIR, f"{vid}-{v.get('redos', 0)}")
    avoid = st.get("recent_voices", []) + ([pkg["voice"]] if pkg.get("voice") else [])
    path, credits = media.make_video(pkg, out, avoid)
    st["recent_voices"] = (st.get("recent_voices", []) + [pkg.get("voice")])[-5:]
    v["package"], v["credits"] = pkg, credits
    tag, ver = f"videos-{vid[:10]}", f"{vid}-v{v.get('redos', 0)}"
    v["file"] = storage.store(path, tag, f"{ver}.mp4")
    thumb = os.path.join(out, "thumbnail.jpg")
    v["thumb"] = storage.store(thumb, tag, f"{ver}-thumb.jpg") if os.path.exists(thumb) else None
    srt_path = os.path.join(out, "captions.srt")
    v["srt"] = open(srt_path, encoding="utf-8").read() if os.path.exists(srt_path) else None
    v["updated"] = state.iso()
    if not config.REQUIRE_APPROVAL:
        v["status"] = "approved"
        return
    v["status"] = "awaiting_approval"
    n = num(vid)
    caption = (f"🎥 <b>Video #{n}</b> · {fmt_label(pkg.get('format'))}\n<b>{esc(pkg['title'])}</b>\n"
               f"{esc(' '.join(pkg['hashtags']))}\n🎙 {esc(pkg.get('voice', ''))}")
    sent = telegram.send_video(path, caption, [[("✅ Publish", f"ok:{vid}"), ("🔁 Redo", f"redo:{vid}")],
                                               [("🎙 New voice", f"voice:{vid}"), ("⏭ Skip", f"no:{vid}")]])
    v["tg_msg"] = sent.get("message_id")
    if os.path.exists(thumb):
        try:
            telegram.send_photo(thumb, f"🖼 Thumbnail for video #{n}")
        except Exception as e:  # noqa: BLE001
            print("thumbnail preview failed:", e)
    auto = (f"⏰ If you don't reply, it auto-publishes in {config.APPROVE_TIMEOUT_HOURS:g}h."
            if config.APPROVE_TIMEOUT_HOURS > 0 else "⏸ It will wait for your reply.")
    others = [k for k, x in st["videos"].items() if x["status"] == "awaiting_approval" and k != vid]
    tip = (f"\n💡 {len(others) + 1} videos are waiting, so add the number (<code>publish {n}</code>) "
           "or reply directly to the video." if others else "")
    opts = telegram.send(
        f"👆 <b>Video #{n} is ready. What would you like to do?</b> Reply with:\n\n"
        f"✅ <code>publish</code>: upload it for the next peak viewing time "
        f"(or <code>publish now</code> to post immediately)\n"
        f"✏️ <code>change</code> + your notes: rewrite it, e.g. <code>change make it funnier</code>, "
        f"<code>change shorter</code>, <code>change turn it into a quiz</code>\n"
        f"🔁 <code>redo</code>: a brand-new version (new script, footage and voice)\n"
        f"🎙 <code>voice</code>: same script, different voice and fresh footage\n"
        f"🏷 <code>title</code> + new title: change only the title\n"
        f"ℹ️ <code>info</code>: see the full description, tags and credits\n"
        f"⏭ <code>skip</code>: throw it away\n\n{auto}{tip}")
    v["opts_msg"] = opts.get("message_id")


def generate(st, vid):
    v = st["videos"][vid]
    ok, issues, pkg = False, [], None
    for _ in range(2):
        pkg = writer.write_package(v["topic"])
        ok, issues = writer.review(pkg)
        if ok:
            break
    if not ok:
        v["status"] = "failed"
        telegram.send(f"🛑 Dropped video #{num(vid)} <b>{esc(v['topic']['title'])}</b>: the safety review flagged "
                      f"{esc('; '.join(map(str, issues))[:300])}. Pick another idea, or /now for new ones.")
        return
    try:
        from . import seo
        pkg["tags"] = seo.build_tags(pkg)
    except Exception as e:  # noqa: BLE001
        print("tag optimizer failed:", e)
    if v["topic"]["title"] not in st["history"]:
        st["history"].append(v["topic"]["title"])
    render_and_preview(st, vid, pkg)


def do_publish(st, vid):
    v = st["videos"][vid]
    pkg = v["package"]
    dl = os.path.join(config.WORK_DIR, "dl")
    path = storage.fetch(v["file"], dl)
    thumb = None
    if v.get("thumb"):
        try:
            thumb = storage.fetch(v["thumb"], dl)
        except Exception as e:  # noqa: BLE001
            print("thumbnail fetch failed:", e)
    srt_path = None
    if v.get("srt"):
        srt_path = os.path.join(dl, f"{vid}.srt")
        os.makedirs(dl, exist_ok=True)
        with open(srt_path, "w", encoding="utf-8") as f:
            f.write(v["srt"])
    desc = writer.build_description(pkg, v.get("credits", []), human_reviewed=v.get("approved_by") == "you")
    v["description_full"] = desc
    slot = None
    if config.SCHEDULE_PUBLISH and not v.get("publish_now"):
        taken = [x.get("slot") for x in st["videos"].values() if x.get("slot")]
        slot = schedule.next_slot(taken)
    results = publish.publish_all(path, pkg["title"], desc, pkg["hashtags"], pkg.get("tags", []),
                                  pkg.get("category", "24"), thumb, srt_path, pkg.get("pinned_comment"),
                                  slot.isoformat().replace("+00:00", "Z") if slot else None)
    v["status"], v["results"], v["updated"] = "published", {k: list(r) for k, r in results.items()}, state.iso()
    v["uploaded_at"] = state.iso()
    if slot:
        v["slot"] = slot.isoformat()
    lines = [f"🚀 <b>Video #{num(vid)} uploaded:</b> {esc(pkg['title'])}"]
    if slot and config.YT_PRIVACY == "public":
        lines.append(f"📅 Goes public automatically at <b>{schedule.fmt_local(slot)}</b> (peak Shorts time).")
    elif slot:
        lines.append(f"📅 Uploaded as private (YouTube API audit pending). Best time to make it public: "
                     f"<b>{schedule.fmt_local(slot)}</b>. Set it in YouTube Studio → Visibility → Schedule.")
    for name, (link, status) in results.items():
        icon = "✅" if link else ("➖" if "skipped" in status else "⚠️")
        if "draft" in status and not link:
            icon = "📥"
        lines.append(f"{icon} {name}: {esc(link or '')} {esc(status)}")
    if "draft" in str((results.get("TikTok") or ("", ""))[1]):
        tk = publish.social_caption(pkg["title"], desc, pkg["hashtags"], "tiktok")
        lines.append("\n📱 <b>Finish on TikTok</b> (1 min): open TikTok → inbox notification → Edit → add a "
                     "trending sound at low volume → paste the caption below → More options → turn on "
                     f"<b>AI-generated content</b> → Post.\n<code>{esc(tk[:900])}</code>")
    yt_link = (results.get("YouTube") or (None, ""))[0]
    if yt_link and pkg.get("pinned_comment") and "comment ✅" in str(results["YouTube"][1]):
        vid_id = yt_link.rsplit("/", 1)[-1]
        lines.append(f"\n📌 I posted your expert comment. YouTube doesn't allow pinning by API, so tap once to pin it:\n"
                     f"https://studio.youtube.com/video/{vid_id}/comments\n<i>{esc(pkg['pinned_comment'])}</i>")
    telegram.send("\n".join(lines))


def uploads_today(st):
    """YouTube quota resets at midnight Pacific time."""
    from zoneinfo import ZoneInfo
    pt = ZoneInfo("America/Los_Angeles")
    day = state.now().astimezone(pt).date()
    return sum(1 for v in st["videos"].values()
               if v.get("status") == "published" and v.get("uploaded_at")
               and state.parse(v["uploaded_at"]).astimezone(pt).date() == day)


def daily_housekeeping(st):
    if st.get("cleanup_day") == today():
        return
    st["cleanup_day"] = today()
    try:
        removed = storage.cleanup(config.KEEP_VIDEOS_DAYS)
        if removed:
            print("Removed old video storage:", removed)
    except Exception as e:  # noqa: BLE001
        print("cleanup failed:", e)


def catch_up_trends(st):
    """If this run's idea list never arrived (GitHub skipped the schedule, AI overloaded...), retry."""
    bid = run_id()
    if bid in st["batches"] or state.now().hour % 6 < 4:  # idea runs fire at ~3:17, 9:17, 15:17, 21:17 UTC
        return
    t = st.get("trend_tries", {}).get(bid)
    if t and (t["n"] >= 3 or state.now() - state.parse(t["at"]) < timedelta(hours=1)):
        return
    print("This run's idea list is missing; retrying trends")
    try:
        cmd_trends(st)
    except Exception as e:  # noqa: BLE001
        traceback.print_exc()
        n = st.get("trend_tries", {}).get(bid, {}).get("n", 1)
        more = "I'll try again in about an hour." if n < 3 else "I'll try at the next run, or send /now."
        telegram.send(f"⚠️ Couldn't build this run's idea list yet ({esc(str(e)[:150])}). {more}")


def cmd_poll(st):
    """Stay online for POLL_MINUTES so Telegram replies are handled within seconds,
    instead of depending on GitHub's (unreliable) schedule for every reply."""
    deadline = time.time() + config.POLL_MINUTES * 60
    first = True
    while True:
        poll_once(st, wait=0 if first else 25)
        state.save(st)
        first = False
        if time.time() >= deadline:
            break


def poll_once(st, wait=0):
    handle_updates(st, wait)
    daily_housekeeping(st)
    try:
        library.refresh_stats()
    except Exception as e:  # noqa: BLE001
        print("stats refresh failed:", e)
    catch_up_trends(st)
    auto_select(st)
    state.save(st)  # save choices before long work
    for vid, v in sorted(st["videos"].items()):
        try:
            if v["status"] in ("queued", "revoice"):
                redo_voice = v["status"] == "revoice"
                v["status"] = "generating"
                state.save(st)
                if redo_voice and v.get("package"):
                    render_and_preview(st, vid, v["package"])
                else:
                    generate(st, vid)
                state.save(st)
                handle_updates(st)  # pick up replies that arrived while rendering
        except Exception as e:  # noqa: BLE001
            traceback.print_exc()
            v["status"] = "failed"
            telegram.send(f"⚠️ Making video #{num(vid)} failed: {esc(str(e)[:300])}")
    for vid, v in sorted(st["videos"].items()):
        if v["status"] == "awaiting_approval" and config.APPROVE_TIMEOUT_HOURS > 0:
            if state.now() - state.parse(v["updated"]) >= timedelta(hours=config.APPROVE_TIMEOUT_HOURS):
                v.update(status="approved", approved_by="auto")
        if v["status"] == "approved":
            if uploads_today(st) >= config.YT_DAILY_UPLOADS:
                if v.get("quota_note") != today():
                    v["quota_note"] = today()
                    telegram.send(f"⏳ Video #{num(vid)} is approved, but today's {config.YT_DAILY_UPLOADS} YouTube uploads "
                                  "are used (free API quota). I'll upload it right after the quota resets at midnight "
                                  "Pacific (3 AM ET); it still goes out at the next peak slot.")
                continue
            try:
                do_publish(st, vid)
            except Exception as e:  # noqa: BLE001
                traceback.print_exc()
                v["status"] = "failed"
                telegram.send(f"⚠️ Publishing video #{num(vid)} failed: {esc(str(e)[:300])}")
            state.save(st)
        # a run that died mid-generation leaves "generating"; retry once after 2h
        if v["status"] == "generating" and state.now() - state.parse(v["updated"]) > timedelta(hours=2):
            v["status"] = "queued"


# ---------------------------------------------------------------- utilities
def cmd_aicheck():
    results = llm.health_check()
    lines = ["🩺 <b>AI services check</b>"]
    for provider, model, ok, detail in results:
        lines.append(f"{'✅' if ok else '❌'} {esc(provider)} · <code>{esc(model)}</code> · {esc(detail)}")
    working = sum(1 for r in results if r[2])
    lines.append(f"\n{working} of {len(results)} working. The bot uses the first working one automatically.")
    print("\n".join(lines))
    telegram.send("\n".join(lines))


SAMPLES = {
    "howitworks": "How revolving doors save energy",
    "why": "Why pilots dim the cabin lights before landing",
    "whatif": "What happens if you fall into quicksand",
    "survival": "What to do if you are caught in a rip current",
    "truestory": "The Great Molasses Flood of 1919 and the sticky street",
    "creature": "The axolotl that can regrow its own limbs",
    "hack": "How to peel a whole head of garlic in 10 seconds",
}


def cmd_test(args):
    fmt = writer.fmt_of({"format": args[0]}) if args else random.choice(list(SAMPLES))
    topic = {"title": " ".join(args[1:]) or SAMPLES[fmt], "angle": "", "format": fmt}
    pkg = writer.write_package(topic)
    print("Review:", writer.review(pkg))
    from . import seo
    pkg["tags"] = seo.build_tags(pkg)
    path, credits = media.make_video(pkg, os.path.join(config.WORK_DIR, "test"))
    desc = writer.build_description(pkg, credits)
    print(pkg["title"], "\n", desc, "\n->", path)
    if config.TELEGRAM_BOT_TOKEN and config.TELEGRAM_CHAT_ID:
        telegram.send_video(path, f"🧪 Test ({fmt_label(fmt)}): <b>{esc(pkg['title'])}</b>\n🎙 {esc(pkg.get('voice'))}"
                                  f" · 🎞 {pkg.get('animated_shots', 0)} animated shots")
        thumb = os.path.join(config.WORK_DIR, "test", "thumbnail.jpg")
        if os.path.exists(thumb):
            telegram.send_photo(thumb, "🖼 Thumbnail")
        telegram.send(f"<b>Title:</b> {esc(pkg['title'])}\n<b>Main keyword:</b> {esc(pkg.get('primary_keyword', ''))}\n"
                      f"<b>Tags ({len(', '.join(pkg.get('tags', [])))} chars):</b> {esc(', '.join(pkg.get('tags', [])))}\n"
                      f"<b>Pinned comment:</b> {esc(pkg.get('pinned_comment', ''))}\n\n"
                      f"<b>Description preview</b>\n\n{esc(desc)[:3200]}")


def main():
    parts = " ".join(sys.argv[1:]).split() or ["poll"]
    cmd, args = parts[0], parts[1:]
    try:
        if cmd == "test":
            return cmd_test(args)
        if cmd == "aicheck":
            return cmd_aicheck()
        if cmd == "stats":
            st = state.load()
            library.refresh_stats(force=True)
            return state.save(st)
        st = state.load()
        try:
            {"trends": cmd_trends, "poll": cmd_poll}[cmd](st)
        finally:
            state.save(st)
    except Exception as e:  # noqa: BLE001
        traceback.print_exc()
        msg = f"{type(e).__name__}: {e}"
        print(f"::error title=autopilot {cmd} failed::{msg[:900]}")  # shows on the GitHub run page
        try:
            telegram.send(f"❌ <b>{esc(cmd)} run failed</b>\n<code>{esc(msg[:900])}</code>")
        except Exception:  # noqa: BLE001
            pass
        sys.exit(1)


if __name__ == "__main__":
    main()
