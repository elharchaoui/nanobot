#!/usr/bin/env python3
"""
Inject Google Analytics 4 tracking into landing pages.

Usage:
  python inject_ga4.py --measurement-id G-XXXXXXXXXX
  python inject_ga4.py --measurement-id G-XXXXXXXXXX --pages-dir /var/www/pages
  python inject_ga4.py --measurement-id G-XXXXXXXXXX --dry-run
"""
import argparse
import sys
from pathlib import Path

GA4_SNIPPET = """\
  <!-- Google Analytics 4 -->
  <script async src="https://www.googletagmanager.com/gtag/js?id={MID}"></script>
  <script>
    window.dataLayer = window.dataLayer || [];
    function gtag(){{dataLayer.push(arguments);}}
    gtag('js', new Date());
    gtag('config', '{MID}');
  </script>"""

FORM_TRACKING = """\
  <script>
    /* GA4 Form Submission Tracking */
    document.addEventListener('DOMContentLoaded', function() {
      document.querySelectorAll('form').forEach(function(form, i) {
        form.addEventListener('submit', function() {
          if (typeof gtag !== 'undefined') {
            gtag('event', 'generate_lead', {
              event_category: 'engagement',
              event_label: 'contact_form_' + (i + 1),
              page_path: window.location.pathname
            });
          }
        });
      });
    });
  </script>"""


def inject(html: str, measurement_id: str) -> tuple[str, bool]:
    """Returns (modified_html, was_modified). Idempotent."""
    if measurement_id in html:
        return html, False

    snippet = GA4_SNIPPET.format(MID=measurement_id)

    if "</head>" in html:
        html = html.replace("</head>", snippet + "\n</head>", 1)
    else:
        # Fallback if no </head>
        html = snippet + "\n" + html

    if "<form" in html.lower() and "</body>" in html:
        html = html.replace("</body>", FORM_TRACKING + "\n</body>", 1)

    return html, True


def main():
    parser = argparse.ArgumentParser(description="Inject GA4 into landing pages")
    parser.add_argument("--measurement-id", required=True, help="GA4 Measurement ID (G-XXXXXXXXXX)")
    parser.add_argument("--pages-dir", default="/var/www/pages", help="Root directory of landing pages")
    parser.add_argument("--dry-run", action="store_true", help="Preview changes without writing files")
    args = parser.parse_args()

    pages_dir = Path(args.pages_dir)
    if not pages_dir.exists():
        print(f"Error: {pages_dir} does not exist", file=sys.stderr)
        sys.exit(1)

    html_files = sorted(pages_dir.rglob("*.html"))
    if not html_files:
        print(f"No HTML files found in {pages_dir}", file=sys.stderr)
        sys.exit(1)

    injected, skipped = 0, 0
    for path in html_files:
        content = path.read_text(encoding="utf-8")
        new_content, changed = inject(content, args.measurement_id)
        if changed:
            if not args.dry_run:
                path.write_text(new_content, encoding="utf-8")
            prefix = "[DRY RUN] " if args.dry_run else ""
            print(f"{prefix}Injected GA4 into: {path}")
            injected += 1
        else:
            print(f"Skipped (already has GA4): {path}")
            skipped += 1

    print(f"\nDone: {injected} injected, {skipped} skipped")


if __name__ == "__main__":
    main()
