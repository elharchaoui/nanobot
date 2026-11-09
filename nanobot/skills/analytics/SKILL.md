---
name: analytics
description: "Track and analyse Google Analytics 4 data for landing pages. Use when the user asks about page views, form submissions, time on page, bounce rate, conversion rates, A/B test comparisons, performance alerts, or any landing page analytics. Also handles first-time GA4 setup and injecting the tracking code."
---

# Analytics Skill

Manages GA4 tracking for landing pages hosted at `/var/www/pages/` (served as `{slug}.pages.heaventy.com`).

Credentials: `~/.nanobot/analytics_credentials.json` (Service Account JSON + `property_id` field).

## One-Time Setup (do this once, then never again)

### Step 1 — Create a GA4 Property

1. Go to https://analytics.google.com → Admin → Create Property
2. Name it (e.g. "Heaventy Pages"), set timezone and currency
3. Choose **Web** platform → enter any domain (e.g. `pages.heaventy.com`)
4. Copy the **Measurement ID** — looks like `G-XXXXXXXXXX`
5. Copy the **Property ID** — numeric only, e.g. `123456789` (Admin → Property Settings)

### Step 2 — Create a Google Cloud Service Account

1. Go to https://console.cloud.google.com → create a project (or reuse one)
2. Enable **Google Analytics Data API**: APIs & Services → Enable APIs → search "Google Analytics Data API"
3. Go to IAM & Admin → Service Accounts → Create Service Account
   - Name: `nanobot-analytics`
   - Skip roles for now → Done
4. Click the service account → Keys tab → Add Key → JSON → Download
5. The downloaded file is your credentials JSON

### Step 3 — Grant Service Account Access to GA4

1. In GA4: Admin → Property → Property Access Management → Add users
2. Paste the service account email (e.g. `nanobot-analytics@your-project.iam.gserviceaccount.com`)
3. Role: **Viewer** → Save

### Step 4 — Store Credentials

Edit the downloaded JSON and add ONE extra field at the top level:
```json
{
  "property_id": "123456789",
  "type": "service_account",
  ...rest of the file unchanged...
}
```

Then save it:
```bash
mkdir -p ~/.nanobot
cp ~/Downloads/your-sa-key.json ~/.nanobot/analytics_credentials.json
chmod 600 ~/.nanobot/analytics_credentials.json
```

### Step 5 — Install Python Dependency

```bash
pip install google-analytics-data
```

### Step 6 — Inject GA4 into All Landing Pages

```bash
python nanobot/skills/analytics/scripts/inject_ga4.py --measurement-id G-XXXXXXXXXX
```

This is idempotent — safe to run multiple times. Adds:
- GA4 pageview tracking (automatic)
- Form submit event (`generate_lead`) on every `<form>` found

**After injecting, wait 24–48 hours before fetching reports** (GA4 data delay).
Real-time data appears within ~30 minutes but has limited metrics.

---

## Fetching Metrics

```bash
# Last 7 days, all pages
python nanobot/skills/analytics/scripts/fetch_metrics.py

# Last 30 days
python nanobot/skills/analytics/scripts/fetch_metrics.py --days 30

# One specific page
python nanobot/skills/analytics/scripts/fetch_metrics.py --page /test-yoga
```

Returns JSON with: `views`, `unique_visitors`, `avg_time_on_page_sec`, `bounce_rate_pct`, `form_submissions`, `conversion_rate_pct` per page.

---

## Scheduled Monitoring (Cron Tasks)

### Daily Alert (every morning at 8am)
```
cron(action="add", message="Fetch analytics for all landing pages (last 2 days). Alert me if: any page has 0 form submissions for 2+ days, bounce rate > 80%, or traffic dropped > 40% vs prior period. Be concise.", cron_expr="0 8 * * *")
```

### Weekly Progress Report (every Monday)
```
cron(action="add", message="Fetch analytics for all landing pages (last 7 days vs 7 days before). Report: top performing page, worst bounce rate, total form submissions this week vs last week. Format as a clear summary.", cron_expr="0 9 * * 1")
```

### Monthly Deep Analysis (1st of month)
```
cron(action="add", message="Fetch analytics for all landing pages (last 30 days). Identify: which page converts best, which has worst engagement, suggest 2-3 specific improvements for the weakest page.", cron_expr="0 10 1 * *")
```

---

## A/B Testing (Simple Two-URL Approach)

No third-party tool needed. Workflow:

1. **Create variant B** — duplicate a landing page directory, change ONE thing (headline, CTA text, hero color):
   ```bash
   cp -r /var/www/pages/test-yoga /var/www/pages/test-yoga-v2
   # Edit /var/www/pages/test-yoga-v2/index.html — change the hero headline only
   python nanobot/skills/analytics/scripts/inject_ga4.py --measurement-id G-XXXXXXXXXX
   ```

2. **Share both URLs** — send `/test-yoga` to half your audience, `/test-yoga-v2` to the other half

3. **Compare after 7+ days**:
   ```
   cron(action="add", message="Compare analytics for /test-yoga vs /test-yoga-v2 (last 14 days). Which has better conversion_rate_pct and lower bounce_rate_pct? Declare a winner and explain why.", at="<ISO date 14 days from now>")
   ```

**Key rule**: Change only ONE element per test. Multiple changes = can't know what caused the difference.

---

## Current Landing Pages

| Slug | URL |
|------|-----|
| `conciergerie-tangier` | https://conciergerie-tangier.pages.heaventy.com |
| `dar-el-medina` | https://dar-el-medina.pages.heaventy.com |
| `test-yoga` | https://test-yoga.pages.heaventy.com |

Pages directory: `/var/www/pages/`
