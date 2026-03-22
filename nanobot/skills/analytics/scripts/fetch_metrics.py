#!/usr/bin/env python3
"""
Fetch GA4 metrics for landing pages via the Analytics Data API.

Credentials file: ~/.nanobot/analytics_credentials.json
  This is the Google Service Account JSON with one extra field added:
    "property_id": "123456789"

Usage:
  python fetch_metrics.py                          # last 7 days, all pages
  python fetch_metrics.py --days 30                # last 30 days
  python fetch_metrics.py --page /test-yoga        # filter to one page
  python fetch_metrics.py --days 7 --compare       # compare all pages side by side
"""
import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

CREDENTIALS_PATH = Path.home() / ".nanobot" / "analytics_credentials.json"


def load_client():
    try:
        from google.analytics.data_v1beta import BetaAnalyticsDataClient
        from google.oauth2 import service_account
    except ImportError:
        print("Error: run  pip install google-analytics-data", file=sys.stderr)
        sys.exit(1)

    if not CREDENTIALS_PATH.exists():
        print(f"Error: credentials not found at {CREDENTIALS_PATH}", file=sys.stderr)
        print("Follow the Service Account setup in the analytics SKILL.md", file=sys.stderr)
        sys.exit(1)

    with open(CREDENTIALS_PATH) as f:
        raw = json.load(f)

    property_id = raw.pop("property_id", None)

    creds = service_account.Credentials.from_service_account_info(
        raw,
        scopes=["https://www.googleapis.com/auth/analytics.readonly"],
    )
    client = BetaAnalyticsDataClient(credentials=creds)
    return client, property_id


def run_report(client, property_id: str, days: int, page_filter: str | None):
    from google.analytics.data_v1beta.types import (
        DateRange, Dimension, Filter, FilterExpression, Metric, RunReportRequest,
    )

    request = RunReportRequest(
        property=f"properties/{property_id}",
        dimensions=[Dimension(name="pagePath"), Dimension(name="pageTitle")],
        metrics=[
            Metric(name="screenPageViews"),
            Metric(name="activeUsers"),
            Metric(name="averageSessionDuration"),
            Metric(name="bounceRate"),
            Metric(name="conversions"),
        ],
        date_ranges=[DateRange(start_date=f"{days}daysAgo", end_date="today")],
    )

    if page_filter:
        request.dimension_filter = FilterExpression(
            filter=Filter(
                field_name="pagePath",
                string_filter=Filter.StringFilter(value=page_filter),
            )
        )

    return client.run_report(request)


def parse_rows(response) -> list[dict]:
    rows = []
    for row in response.rows:
        path = row.dimension_values[0].value
        title = row.dimension_values[1].value
        views = int(row.metric_values[0].value or 0)
        users = int(row.metric_values[1].value or 0)
        duration = float(row.metric_values[2].value or 0)
        bounce = float(row.metric_values[3].value or 0)
        conversions = int(row.metric_values[4].value or 0)
        rows.append({
            "page": path,
            "title": title,
            "views": views,
            "unique_visitors": users,
            "avg_time_on_page_sec": round(duration, 1),
            "bounce_rate_pct": round(bounce * 100, 1),
            "form_submissions": conversions,
            "conversion_rate_pct": round(conversions / users * 100, 2) if users > 0 else 0.0,
        })
    rows.sort(key=lambda x: x["views"], reverse=True)
    return rows


def main():
    parser = argparse.ArgumentParser(description="Fetch GA4 metrics for landing pages")
    parser.add_argument("--property-id", help="GA4 numeric Property ID (overrides credentials file)")
    parser.add_argument("--days", type=int, default=7, help="Days to look back (default: 7)")
    parser.add_argument("--page", help="Filter by page path, e.g. /test-yoga")
    args = parser.parse_args()

    client, stored_pid = load_client()
    property_id = args.property_id or stored_pid
    if not property_id:
        print("Error: provide --property-id or add 'property_id' to credentials file", file=sys.stderr)
        sys.exit(1)

    response = run_report(client, property_id, args.days, args.page)
    pages = parse_rows(response)

    output = {
        "fetched_at": datetime.utcnow().isoformat() + "Z",
        "period_days": args.days,
        "summary": {
            "total_views": sum(p["views"] for p in pages),
            "total_unique_visitors": sum(p["unique_visitors"] for p in pages),
            "total_form_submissions": sum(p["form_submissions"] for p in pages),
        },
        "pages": pages,
    }

    print(json.dumps(output, indent=2))


if __name__ == "__main__":
    main()
