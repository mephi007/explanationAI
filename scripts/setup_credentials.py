"""
setup_credentials.py — Run this ONCE locally to get all OAuth tokens.
Each section is independent — run only what you need.

Usage:
  python scripts/setup_credentials.py --linkedin
  python scripts/setup_credentials.py --youtube
  python scripts/setup_credentials.py --telegram
  python scripts/setup_credentials.py --all
"""

import sys
import argparse
import urllib.parse
import http.server
import webbrowser
import requests
import threading
import json


# ─── LinkedIn ────────────────────────────────────────────────────────────────

def setup_linkedin():
    print("\n" + "="*60)
    print("  LinkedIn OAuth Setup")
    print("="*60)
    print("\nPrerequisites:")
    print("  1. Create app at linkedin.com/developers")
    print("  2. Add products: 'Share on LinkedIn' + 'Sign In with LinkedIn'")
    print("  3. Set redirect URI to: http://localhost:8765/callback\n")

    client_id     = input("Client ID: ").strip()
    client_secret = input("Client Secret: ").strip()
    redirect_uri  = "http://localhost:8765/callback"
    scopes        = "w_member_social r_liteprofile"

    auth_url = (
        "https://www.linkedin.com/oauth/v2/authorization"
        f"?response_type=code&client_id={client_id}"
        f"&redirect_uri={urllib.parse.quote(redirect_uri)}"
        f"&scope={urllib.parse.quote(scopes)}&state=dsa-bot"
    )

    auth_code = [None]

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            params = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(self.path).query))
            auth_code[0] = params.get("code")
            self.send_response(200); self.end_headers()
            self.wfile.write(b"<h2>LinkedIn auth done! Close this tab.</h2>")
        def log_message(self, *args): pass

    server = http.server.HTTPServer(("localhost", 8765), Handler)
    print(f"Opening browser...")
    webbrowser.open(auth_url)
    server.handle_request()

    if not auth_code[0]:
        print("ERROR: No auth code received."); return

    resp = requests.post("https://www.linkedin.com/oauth/v2/accessToken", data={
        "grant_type": "authorization_code",
        "code": auth_code[0],
        "redirect_uri": redirect_uri,
        "client_id": client_id,
        "client_secret": client_secret,
    })
    resp.raise_for_status()
    token = resp.json()["access_token"]
    expires = resp.json().get("expires_in", "unknown")

    me = requests.get("https://api.linkedin.com/v2/me",
                      headers={"Authorization": f"Bearer {token}"})
    person_id = me.json().get("id", "UNKNOWN")
    person_urn = f"urn:li:person:{person_id}"

    print(f"""
╔══════════════════════════════════════════════════════╗
  Add to GitHub Secrets → Settings → Secrets → Actions
╠══════════════════════════════════════════════════════╣
  LINKEDIN_ACCESS_TOKEN  = {token}
  LINKEDIN_PERSON_URN    = {person_urn}
  Token expires in: {expires}s (~60 days — re-run when expired)
╚══════════════════════════════════════════════════════╝""")


# ─── YouTube ─────────────────────────────────────────────────────────────────

def setup_youtube():
    print("\n" + "="*60)
    print("  YouTube OAuth Setup")
    print("="*60)
    print("\nPrerequisites:")
    print("  1. Go to console.cloud.google.com")
    print("  2. Enable YouTube Data API v3")
    print("  3. Create OAuth 2.0 credentials (Desktop app)")
    print("  4. Set redirect URI: http://localhost:8766/callback\n")

    client_id     = input("Client ID: ").strip()
    client_secret = input("Client Secret: ").strip()
    redirect_uri  = "http://localhost:8766/callback"
    scope = "https://www.googleapis.com/auth/youtube.upload"

    auth_url = (
        "https://accounts.google.com/o/oauth2/v2/auth"
        f"?response_type=code&client_id={client_id}"
        f"&redirect_uri={urllib.parse.quote(redirect_uri)}"
        f"&scope={urllib.parse.quote(scope)}"
        f"&access_type=offline&prompt=consent"
    )

    auth_code = [None]

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            params = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(self.path).query))
            auth_code[0] = params.get("code")
            self.send_response(200); self.end_headers()
            self.wfile.write(b"<h2>YouTube auth done! Close this tab.</h2>")
        def log_message(self, *args): pass

    server = http.server.HTTPServer(("localhost", 8766), Handler)
    print("Opening browser...")
    webbrowser.open(auth_url)
    server.handle_request()

    resp = requests.post("https://oauth2.googleapis.com/token", data={
        "code": auth_code[0],
        "client_id": client_id,
        "client_secret": client_secret,
        "redirect_uri": redirect_uri,
        "grant_type": "authorization_code",
    })
    resp.raise_for_status()
    data = resp.json()
    refresh_token = data.get("refresh_token", "")

    if not refresh_token:
        print("WARNING: No refresh_token returned. Revoke app at myaccount.google.com/permissions and re-run.")

    print(f"""
╔══════════════════════════════════════════════════════╗
  Add to GitHub Secrets
╠══════════════════════════════════════════════════════╣
  YOUTUBE_CLIENT_ID      = {client_id}
  YOUTUBE_CLIENT_SECRET  = {client_secret}
  YOUTUBE_REFRESH_TOKEN  = {refresh_token or 'NOT RECEIVED - re-run'}
  Refresh token never expires unless revoked.
╚══════════════════════════════════════════════════════╝""")


# ─── Telegram ────────────────────────────────────────────────────────────────

def setup_telegram():
    print("\n" + "="*60)
    print("  Telegram Bot Setup")
    print("="*60)
    print("""
Steps:
  1. Open Telegram → search @BotFather → /newbot
  2. Choose a name (e.g. "DSA Content Bot") and username (e.g. dsa_content_bot)
  3. BotFather gives you a token — paste it below
  4. Start a chat with your new bot → send /start
  5. Then we'll get your chat ID automatically
""")
    bot_token = input("Bot token from BotFather: ").strip()

    print("\nNow send any message to your bot in Telegram, then press Enter here...")
    input("(Press Enter after sending a message to your bot)")

    resp = requests.get(f"https://api.telegram.org/bot{bot_token}/getUpdates")
    resp.raise_for_status()
    updates = resp.json().get("result", [])

    if not updates:
        print("No messages found. Make sure you sent a message to the bot first.")
        return

    chat_id = updates[-1]["message"]["chat"]["id"]
    # Test send
    requests.post(f"https://api.telegram.org/bot{bot_token}/sendMessage",
                  json={"chat_id": chat_id, "text": "✅ DSA Content Bot connected! You'll get daily content previews here."})

    print(f"""
╔══════════════════════════════════════════════════════╗
  Add to GitHub Secrets
╠══════════════════════════════════════════════════════╣
  TELEGRAM_BOT_TOKEN = {bot_token}
  TELEGRAM_CHAT_ID   = {chat_id}
╚══════════════════════════════════════════════════════╝""")


# ─── Instagram ───────────────────────────────────────────────────────────────

def setup_instagram():
    print("\n" + "="*60)
    print("  Instagram / Meta Graph API Setup")
    print("="*60)
    print("""
Steps:
  1. Go to developers.facebook.com → Create App → Business type
  2. Add product: Instagram Graph API
  3. Convert your Instagram to Business account (IG Settings → Account → Switch)
  4. Connect IG Business account to your Facebook Page
  5. Get a long-lived access token from Graph API Explorer:
     - Tool: developers.facebook.com/tools/explorer
     - Select your app → Generate User Token
     - Permissions: instagram_basic, instagram_content_publish, pages_show_list
  6. Exchange for long-lived token (60 days):
""")
    short_token = input("Short-lived token from Graph Explorer: ").strip()
    app_id      = input("App ID: ").strip()
    app_secret  = input("App Secret: ").strip()

    # Exchange for long-lived
    resp = requests.get(
        "https://graph.facebook.com/v19.0/oauth/access_token",
        params={
            "grant_type": "fb_exchange_token",
            "client_id": app_id,
            "client_secret": app_secret,
            "fb_exchange_token": short_token,
        }
    )
    resp.raise_for_status()
    long_token = resp.json()["access_token"]

    # Get IG Business Account ID
    pages_resp = requests.get(
        "https://graph.facebook.com/v19.0/me/accounts",
        params={"access_token": long_token}
    )
    pages = pages_resp.json().get("data", [])
    if not pages:
        print("No Facebook Pages found. Make sure IG is linked to a Page.")
        return

    page = pages[0]
    page_token = page.get("access_token", long_token)

    ig_resp = requests.get(
        f"https://graph.facebook.com/v19.0/{page['id']}",
        params={"fields": "instagram_business_account", "access_token": page_token}
    )
    ig_id = ig_resp.json().get("instagram_business_account", {}).get("id", "NOT_FOUND")

    print(f"""
╔══════════════════════════════════════════════════════╗
  Add to GitHub Secrets
╠══════════════════════════════════════════════════════╣
  INSTAGRAM_ACCESS_TOKEN         = {long_token}
  INSTAGRAM_BUSINESS_ACCOUNT_ID  = {ig_id}
  Token expires in 60 days — re-run setup when expired.
╚══════════════════════════════════════════════════════╝""")


# ─── Main ────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Setup OAuth credentials for DSA Content Engine")
    parser.add_argument("--linkedin",  action="store_true")
    parser.add_argument("--youtube",   action="store_true")
    parser.add_argument("--telegram",  action="store_true")
    parser.add_argument("--instagram", action="store_true")
    parser.add_argument("--all",       action="store_true")
    args = parser.parse_args()

    if args.all or args.telegram:  setup_telegram()
    if args.all or args.linkedin:  setup_linkedin()
    if args.all or args.youtube:   setup_youtube()
    if args.all or args.instagram: setup_instagram()

    if not any(vars(args).values()):
        parser.print_help()
