"""Run ONCE to connect your Facebook Page + Instagram professional account (no expiry).

Before running (details in the setup guide):
 1. developers.facebook.com > My Apps > Create app (Business type). Note the App ID and App secret
    (App settings > Basic).
 2. Tools > Graph API Explorer: pick your app, "Get User Access Token" with these permissions:
    pages_show_list, pages_read_engagement, pages_manage_posts, business_management,
    instagram_basic, instagram_content_publish. Approve for your Page + Instagram account. Copy the token.
 3. python get_meta_token.py   (paste the 3 values when asked)

It prints FB_PAGE_ID, FB_PAGE_TOKEN and IG_USER_ID for GitHub Secrets. Page tokens made from a
long-lived user token don't expire (they stop working only if you change your password or remove the app).
"""
import requests

G = "https://graph.facebook.com/v23.0"
app_id = input("App ID: ").strip()
app_secret = input("App secret: ").strip()
short = input("User access token from Graph API Explorer: ").strip()

r = requests.get(f"{G}/oauth/access_token", params={
    "grant_type": "fb_exchange_token", "client_id": app_id, "client_secret": app_secret,
    "fb_exchange_token": short}, timeout=30).json()
if "access_token" not in r:
    raise SystemExit(f"Could not get a long-lived token: {r}")
long_user = r["access_token"]

pages = requests.get(f"{G}/me/accounts", params={
    "fields": "id,name,access_token,instagram_business_account{id,username}",
    "access_token": long_user}, timeout=30).json().get("data", [])
if not pages:
    raise SystemExit("No Pages found. Make sure you selected your Page when approving the token.")
for i, p in enumerate(pages, 1):
    ig = p.get("instagram_business_account") or {}
    print(f"{i}. {p['name']}  (Instagram: @{ig.get('username', 'not linked')})")
pick = pages[int(input("Which Page? number: ") or 1) - 1] if len(pages) > 1 else pages[0]
ig = pick.get("instagram_business_account") or {}

print("\nAdd these as GitHub Secrets (repo > Settings > Secrets and variables > Actions):")
print("FB_PAGE_ID    =", pick["id"])
print("FB_PAGE_TOKEN =", pick["access_token"])
print("IG_USER_ID    =", ig.get("id", "(Instagram not linked to this Page yet - link it, then re-run)"))
