#!/usr/bin/env python3
"""
LinkedIn OAuth 2.0 setup — run once per app to authorize nanobot.

Usage:
    # Main app (posting + profile):
    python3 auth.py --client-id <id> --client-secret <secret> --manual

    # Community app (read posts + comment):
    python3 auth.py --client-id <id> --client-secret <secret> --app community --manual

Reads/writes ~/.nanobot/linkedin.json
"""

import argparse
import json
import secrets
import sys
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse

import httpx

CONFIG_PATH = Path.home() / ".nanobot" / "linkedin.json"
REDIRECT_URI = "http://localhost:8765/callback"
AUTH_URL = "https://www.linkedin.com/oauth/v2/authorization"
TOKEN_URL = "https://www.linkedin.com/oauth/v2/accessToken"

SCOPES = {
    "main": "openid profile email w_member_social",
    "community": "r_member_social w_member_social",
}


def load_config() -> dict:
    if CONFIG_PATH.exists():
        return json.loads(CONFIG_PATH.read_text())
    return {}


def save_config(data: dict) -> None:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(data, indent=2))
    print(f"Saved to {CONFIG_PATH}")


def exchange_code(client_id: str, client_secret: str, code: str) -> dict:
    resp = httpx.post(
        TOKEN_URL,
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": REDIRECT_URI,
            "client_id": client_id,
            "client_secret": client_secret,
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()


def fetch_profile(access_token: str) -> dict:
    resp = httpx.get(
        "https://api.linkedin.com/v2/userinfo",
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()


def run_auth_manual(client_id: str, scopes: str) -> str:
    """Print the auth URL and ask the user to paste the redirect URL back."""
    state = secrets.token_urlsafe(16)
    params = urlencode({
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": REDIRECT_URI,
        "scope": scopes,
        "state": state,
    })
    auth_url = f"{AUTH_URL}?{params}"

    print("\n--- LinkedIn Authorization ---")
    print("Open this URL in your browser:\n")
    print(f"  {auth_url}\n")
    print("After approving, your browser will fail to connect (that's expected).")
    print("Copy the full URL from the browser's address bar and paste it here.\n")

    redirect_url = input("Paste the redirect URL: ").strip()
    parsed = urlparse(redirect_url)
    qs = parse_qs(parsed.query)

    if "error" in qs:
        print(f"Authorization error: {qs['error'][0]}")
        sys.exit(1)
    if "code" not in qs:
        print("No 'code' found in the URL. Make sure you copied the full URL.")
        sys.exit(1)
    if qs.get("state", [""])[0] != state:
        print("State mismatch — possible CSRF. Aborting.")
        sys.exit(1)

    return qs["code"][0]


def run_auth_local_server(client_id: str, scopes: str) -> str:
    """Start a local HTTP server to catch the OAuth callback automatically."""
    state = secrets.token_urlsafe(16)
    received: dict = {}
    server_done = threading.Event()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            parsed = urlparse(self.path)
            params = parse_qs(parsed.query)
            if parsed.path == "/callback":
                if "error" in params:
                    received["error"] = params["error"][0]
                elif "code" in params:
                    received["code"] = params["code"][0]
                    received["state"] = params.get("state", [""])[0]
                self.send_response(200)
                self.send_header("Content-Type", "text/html")
                self.end_headers()
                body = b"<h2>Done! You can close this tab.</h2>" if "code" in received else b"<h2>Authorization failed.</h2>"
                self.wfile.write(body)
                server_done.set()

    server = HTTPServer(("localhost", 8765), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    params = urlencode({
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": REDIRECT_URI,
        "scope": scopes,
        "state": state,
    })
    auth_url = f"{AUTH_URL}?{params}"
    print("\nOpening LinkedIn authorization in your browser...")
    print(f"If it doesn't open automatically, visit:\n  {auth_url}\n")
    webbrowser.open(auth_url)

    server_done.wait(timeout=120)
    server.shutdown()

    if "error" in received:
        print(f"Error: {received['error']}")
        sys.exit(1)
    if "code" not in received:
        print("Timed out waiting for authorization callback.")
        sys.exit(1)
    if received.get("state") != state:
        print("State mismatch — possible CSRF. Aborting.")
        sys.exit(1)

    return received["code"]


def run_auth(client_id: str, client_secret: str, app: str, manual: bool) -> None:
    scopes = SCOPES[app]
    print(f"\nAuthorizing '{app}' app with scopes: {scopes}")

    if manual:
        code = run_auth_manual(client_id, scopes)
    else:
        code = run_auth_local_server(client_id, scopes)

    print("Exchanging authorization code for access token...")
    token_data = exchange_code(client_id, client_secret, code)
    access_token = token_data["access_token"]

    config = load_config()

    if app == "main":
        print("Fetching your LinkedIn profile...")
        profile = fetch_profile(access_token)
        person_id = profile.get("sub", "")
        name = profile.get("name", "unknown")
        config.update({
            "client_id": client_id,
            "client_secret": client_secret,
            "access_token": access_token,
            "person_id": person_id,
            "name": name,
        })
        print(f"\nMain app authenticated as: {name} (person ID: {person_id})")
    else:
        config.update({
            "community_client_id": client_id,
            "community_client_secret": client_secret,
            "community_access_token": access_token,
        })
        print(f"\nCommunity app authenticated successfully.")

    save_config(config)
    print("Done!")


def main():
    parser = argparse.ArgumentParser(description="Authorize nanobot to access LinkedIn")
    parser.add_argument("--client-id", help="LinkedIn app Client ID")
    parser.add_argument("--client-secret", help="LinkedIn app Client Secret")
    parser.add_argument("--app", choices=["main", "community"], default="main",
                        help="Which app to authorize: 'main' (post/profile) or 'community' (read/comment)")
    parser.add_argument("--manual", action="store_true",
                        help="Paste redirect URL manually (use this on cloud/remote servers)")
    args = parser.parse_args()

    config = load_config()
    id_key = "client_id" if args.app == "main" else "community_client_id"
    secret_key = "client_secret" if args.app == "main" else "community_client_secret"

    client_id = args.client_id or config.get(id_key) or input("Client ID: ").strip()
    client_secret = args.client_secret or config.get(secret_key) or input("Client Secret: ").strip()

    if not client_id or not client_secret:
        print("Client ID and Client Secret are required.")
        sys.exit(1)

    run_auth(client_id, client_secret, app=args.app, manual=args.manual)


if __name__ == "__main__":
    main()
