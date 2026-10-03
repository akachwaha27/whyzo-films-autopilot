"""Minimal Telegram Bot API client (no extra libraries)."""
import json

import requests

from . import config

API = "https://api.telegram.org/bot{token}/{method}"


def _call(method, files=None, **params):
    """params go to Telegram as-is (including Telegram's own 'timeout' for getUpdates)."""
    url = API.format(token=config.TELEGRAM_BOT_TOKEN, method=method)
    if files:
        r = requests.post(url, data=params, files=files, timeout=600)
    else:
        r = requests.post(url, json=params, timeout=60)
    data = r.json()
    if not data.get("ok"):
        raise RuntimeError(f"Telegram {method} failed: {data}")
    return data["result"]


def send(text, buttons=None):
    """buttons: list of rows, each row a list of (label, callback_data)."""
    params = {"chat_id": config.TELEGRAM_CHAT_ID, "text": text[:4000],
              "parse_mode": "HTML", "disable_web_page_preview": True}
    if buttons:
        params["reply_markup"] = {"inline_keyboard": [
            [{"text": t, "callback_data": d} for t, d in row] for row in buttons]}
    return _call("sendMessage", **params)


def send_video(path, caption, buttons=None):
    data = {"chat_id": config.TELEGRAM_CHAT_ID, "caption": caption[:1000],
            "parse_mode": "HTML", "supports_streaming": "true"}
    if buttons:
        data["reply_markup"] = json.dumps({"inline_keyboard": [
            [{"text": t, "callback_data": d} for t, d in row] for row in buttons]})
    with open(path, "rb") as f:
        return _call("sendVideo", files={"video": f}, **data)


def send_photo(path, caption=""):
    with open(path, "rb") as f:
        return _call("sendPhoto", files={"photo": f}, chat_id=config.TELEGRAM_CHAT_ID,
                     caption=caption[:1000], parse_mode="HTML")


def updates(offset, wait=0):
    """wait > 0 long-polls: Telegram holds the request until a message arrives (max `wait` s)."""
    return _call("getUpdates", offset=offset, timeout=wait, allowed_updates=["message", "callback_query"])


def answer_callback(cb_id, text=""):
    try:
        _call("answerCallbackQuery", callback_query_id=cb_id, text=text)
    except Exception:
        pass  # callbacks older than ~15 min can't be answered; harmless
