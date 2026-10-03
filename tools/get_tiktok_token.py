"""Run ONCE to get a TikTok refresh token (valid ~1 year; re-run yearly).

Prereqs: TikTok for Developers app with Login Kit + Content Posting API,
scopes user.info.basic + video.upload (draft mode; add video.publish for direct mode),
Redirect URI: https://akachwaha27.github.io/whyzo-films-autopilot/callback.html

  python tools/get_tiktok_token.py
Open the printed URL, approve, then paste the FULL URL you were redirected to.
"""
import secrets
import urllib.parse

import requests

key = input("TikTok client key: ").strip()
secret = input("TikTok client secret: ").strip()
redirect = input("Redirect URI [https://akachwaha27.github.io/whyzo-films-autopilot/callback.html]: ").strip() \
    or "https://akachwaha27.github.io/whyzo-films-autopilot/callback.html"
scope = "user.info.basic,video.upload" + (",video.publish" if input("Also allow direct posting? (y/N): ").strip().lower() == "y" else "")
state = secrets.token_urlsafe(8)
url = "https://www.tiktok.com/v2/auth/authorize/?" + urllib.parse.urlencode({
    "client_key": key, "response_type": "code", "scope": scope,
    "redirect_uri": redirect, "state": state})
print("\nOpen this URL and approve:\n", url)
back = input("\nPaste the full URL shown on the page you land on: ").strip()
code = urllib.parse.parse_qs(urllib.parse.urlparse(back).query)["code"][0]
r = requests.post("https://open.tiktokapis.com/v2/oauth/token/", data={
    "client_key": key, "client_secret": secret, "code": code,
    "grant_type": "authorization_code", "redirect_uri": redirect}).json()
print("\nTIKTOK_CLIENT_KEY    =", key)
print("TIKTOK_CLIENT_SECRET =", secret)
print("TIKTOK_REFRESH_TOKEN =", r.get("refresh_token"), "\n", r if "refresh_token" not in r else "")
