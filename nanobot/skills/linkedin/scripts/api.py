#!/usr/bin/env python3
"""
LinkedIn API client for nanobot.

Uses two apps:
  - Main app token     → profile, post
  - Community app token → my-posts, comment

Usage:
    python3 api.py profile
    python3 api.py post "Your update text here"
    python3 api.py my-posts [--limit 5]
    python3 api.py comment <post-urn> "Your comment text"

Config is read from ~/.nanobot/linkedin.json (populated by auth.py).
"""

import argparse
import json
import sys
from pathlib import Path

import httpx

CONFIG_PATH = Path.home() / ".nanobot" / "linkedin.json"
API_BASE = "https://api.linkedin.com/v2"


def load_config() -> dict:
    if not CONFIG_PATH.exists():
        print("LinkedIn not configured. Run auth.py first.", file=sys.stderr)
        sys.exit(1)
    return json.loads(CONFIG_PATH.read_text())


def main_headers(cfg: dict) -> dict:
    return {
        "Authorization": f"Bearer {cfg['access_token']}",
        "Content-Type": "application/json",
        "X-Restli-Protocol-Version": "2.0.0",
    }


def community_headers(cfg: dict) -> dict:
    token = cfg.get("community_access_token")
    if not token:
        print(json.dumps({
            "error": "community_app_not_configured",
            "detail": "Run: python3 auth.py --app community --manual",
        }))
        sys.exit(1)
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "X-Restli-Protocol-Version": "2.0.0",
    }


def cmd_profile(cfg: dict) -> None:
    """Print your LinkedIn profile summary."""
    resp = httpx.get(
        f"{API_BASE}/userinfo",
        headers=main_headers(cfg),
        timeout=10,
    )
    resp.raise_for_status()
    data = resp.json()
    print(json.dumps({
        "name": data.get("name"),
        "email": data.get("email"),
        "person_id": data.get("sub"),
        "picture": data.get("picture"),
    }, indent=2))


def upload_image(cfg: dict, image_path: str) -> str:
    """Upload an image to LinkedIn and return the asset URN."""
    person_urn = f"urn:li:person:{cfg['person_id']}"

    # Step 1: Register upload
    register_payload = {
        "registerUploadRequest": {
            "recipes": ["urn:li:digitalmediaRecipe:feedshare-image"],
            "owner": person_urn,
            "serviceRelationships": [{
                "relationshipType": "OWNER",
                "identifier": "urn:li:userGeneratedContent",
            }],
        }
    }
    resp = httpx.post(
        f"{API_BASE}/assets?action=registerUpload",
        headers=main_headers(cfg),
        json=register_payload,
        timeout=15,
    )
    resp.raise_for_status()
    data = resp.json()
    upload_url = data["value"]["uploadMechanism"]["com.linkedin.digitalmedia.uploading.MediaUploadHttpRequest"]["uploadUrl"]
    asset_urn = data["value"]["asset"]

    # Step 2: Upload image binary
    with open(image_path, "rb") as f:
        image_data = f.read()
    upload_resp = httpx.put(
        upload_url,
        content=image_data,
        headers={"Content-Type": "application/octet-stream"},
        timeout=60,
    )
    upload_resp.raise_for_status()

    return asset_urn


def cmd_post(cfg: dict, text: str, image: str | None = None) -> None:
    """Share a text update on LinkedIn, optionally with an image."""
    person_urn = f"urn:li:person:{cfg['person_id']}"

    if image:
        asset_urn = upload_image(cfg, image)
        share_content = {
            "shareCommentary": {"text": text},
            "shareMediaCategory": "IMAGE",
            "media": [{
                "status": "READY",
                "media": asset_urn,
            }],
        }
    else:
        share_content = {
            "shareCommentary": {"text": text},
            "shareMediaCategory": "NONE",
        }

    payload = {
        "author": person_urn,
        "lifecycleState": "PUBLISHED",
        "specificContent": {"com.linkedin.ugc.ShareContent": share_content},
        "visibility": {"com.linkedin.ugc.MemberNetworkVisibility": "PUBLIC"},
    }
    resp = httpx.post(
        f"{API_BASE}/ugcPosts",
        headers=main_headers(cfg),
        json=payload,
        timeout=15,
    )
    resp.raise_for_status()
    post_id = resp.headers.get("x-restli-id", "unknown")
    print(json.dumps({"status": "posted", "post_id": post_id}))


def cmd_my_posts(cfg: dict, limit: int) -> None:
    """List your recent posts (uses community app token)."""
    person_urn = f"urn:li:person:{cfg['person_id']}"
    resp = httpx.get(
        f"{API_BASE}/ugcPosts",
        params={
            "q": "authors",
            "authors": f"List({person_urn})",
            "count": limit,
        },
        headers=community_headers(cfg),
        timeout=10,
    )
    resp.raise_for_status()
    data = resp.json()
    posts = []
    for item in data.get("elements", []):
        share = item.get("specificContent", {}).get("com.linkedin.ugc.ShareContent", {})
        commentary = share.get("shareCommentary", {}).get("text", "")
        posts.append({
            "id": item.get("id"),
            "text": commentary[:200] + ("..." if len(commentary) > 200 else ""),
            "created": item.get("created", {}).get("time"),
            "lifecycle": item.get("lifecycleState"),
        })
    print(json.dumps(posts, indent=2))


def cmd_comment(cfg: dict, post_urn: str, text: str) -> None:
    """Comment on a post (uses community app token)."""
    person_urn = f"urn:li:person:{cfg['person_id']}"
    payload = {
        "actor": person_urn,
        "message": {"text": text},
        "object": post_urn,
    }
    resp = httpx.post(
        f"{API_BASE}/socialActions/{post_urn}/comments",
        headers=community_headers(cfg),
        json=payload,
        timeout=15,
    )
    resp.raise_for_status()
    print(json.dumps({"status": "commented"}))


def main():
    parser = argparse.ArgumentParser(description="LinkedIn API client for nanobot")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("profile", help="Show your LinkedIn profile")

    p = sub.add_parser("post", help="Share a text update, optionally with an image")
    p.add_argument("text", help="Post content")
    p.add_argument("--image", help="Path to image file (jpg, png, gif)", default=None)

    mp = sub.add_parser("my-posts", help="List your recent posts")
    mp.add_argument("--limit", type=int, default=5)

    c = sub.add_parser("comment", help="Comment on a post")
    c.add_argument("post_urn", help="Post URN (e.g. urn:li:ugcPost:123456)")
    c.add_argument("text", help="Comment text")

    args = parser.parse_args()
    cfg = load_config()

    try:
        if args.command == "profile":
            cmd_profile(cfg)
        elif args.command == "post":
            cmd_post(cfg, args.text, image=args.image)
        elif args.command == "my-posts":
            cmd_my_posts(cfg, args.limit)
        elif args.command == "comment":
            cmd_comment(cfg, args.post_urn, args.text)
    except httpx.HTTPStatusError as e:
        print(json.dumps({
            "error": str(e),
            "status_code": e.response.status_code,
            "detail": e.response.text[:500],
        }), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
