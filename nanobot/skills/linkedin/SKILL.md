---
name: linkedin
description: "Interact with LinkedIn: post updates, read your profile, list your posts, and comment. Use when the user wants to share something on LinkedIn, check their LinkedIn profile, view their posts, or engage with LinkedIn content."
---

# LinkedIn Skill

Uses two LinkedIn apps whose tokens are stored in `~/.nanobot/linkedin.json`.
Scripts live at `nanobot/skills/linkedin/scripts/`.

| App | Scopes | Operations |
|-----|--------|------------|
| Main | `openid profile email w_member_social` | `profile`, `post` |
| Community | `r_member_social w_member_social` | `my-posts`, `comment` |

## Setup (one-time per app)

**Main app** (posting + profile):
```bash
python3 nanobot/skills/linkedin/scripts/auth.py --client-id <id> --client-secret <secret> --manual
```

**Community app** (read posts + comment):
```bash
python3 nanobot/skills/linkedin/scripts/auth.py --client-id <id> --client-secret <secret> --app community --manual
```

## Operations

### Get profile (main app)
```bash
python3 nanobot/skills/linkedin/scripts/api.py profile
```

### Post an update (main app)
```bash
# Text only
python3 nanobot/skills/linkedin/scripts/api.py post "Your update text here"

# With image
python3 nanobot/skills/linkedin/scripts/api.py post "Your update text here" --image /path/to/image.jpg
```

Always confirm the post text (and image path) with the user before posting.

### List recent posts (community app)
```bash
python3 nanobot/skills/linkedin/scripts/api.py my-posts --limit 5
```

### Comment on a post (community app)
```bash
python3 nanobot/skills/linkedin/scripts/api.py comment "urn:li:ugcPost:123456" "Great post!"
```

## Notes

- If you get a 401, re-run `auth.py` for the relevant app to refresh the token.
- `community_app_not_configured` error means the community app auth hasn't been run yet.
- Posts are PUBLIC by default.
