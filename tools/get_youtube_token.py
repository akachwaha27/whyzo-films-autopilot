"""Run ONCE on your own computer to get a YouTube refresh token.

1. Google Cloud Console > APIs & Services > Credentials > Create OAuth client ID > "Desktop app".
2. Download the JSON as client_secret.json next to this file.
3. pip install google-auth-oauthlib && python tools/get_youtube_token.py
4. Sign in with the Google account that owns your channel. Copy the 3 printed values into GitHub Secrets.
"""
import json

from google_auth_oauthlib.flow import InstalledAppFlow

flow = InstalledAppFlow.from_client_secrets_file(
    "client_secret.json", scopes=["https://www.googleapis.com/auth/youtube.upload",
                                  "https://www.googleapis.com/auth/youtube.force-ssl"])  # force-ssl: subtitles
creds = flow.run_local_server(port=0, access_type="offline", prompt="consent")
info = json.loads(creds.to_json())
print("\nYT_CLIENT_ID     =", info["client_id"])
print("YT_CLIENT_SECRET =", info["client_secret"])
print("YT_REFRESH_TOKEN =", info["refresh_token"])
