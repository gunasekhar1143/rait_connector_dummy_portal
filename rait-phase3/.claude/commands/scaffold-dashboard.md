---
description: Scaffold a Jinja2 dashboard template, vanilla JS polling, and CSS for a RAIT portal module. Pass the module name and any extra data fields it should display.
argument-hint: "<module-name> [extra field descriptions]"
allowed-tools: Write, Read, Glob
---

Generate a Jinja2 HTML dashboard template and accompanying static assets for:

$ARGUMENTS

Files to generate (write all three):
1. dummy_portal/ui/templates/dashboard.html — Jinja2 template extending base.html
2. dummy_portal/ui/static/js/dashboard.js — vanilla JS polling logic
3. dummy_portal/ui/static/css/dashboard.css — layout and badge styles

Requirements:
- dashboard.html: iterate over {{ dimensions }} list — NO hardcoded dimension names or card count
- Each dimension card: dimension_name, score formatted as "XX.X%", is_safe badge, sample_count
- Record table: last 20 ingest_records with model_name, log_type, received_at, href to /records/{id}
- dashboard.js: setInterval(refreshDashboard, 10000); fetch /api/dimensions/summary; update card
  elements by dimension_id (use data-dimension-id attributes on card elements)
- CSS: safe badge color #2ecc71, unsafe badge #e74c3c, 3-column grid for dimension cards,
  responsive (collapse to 1 column below 768px)
- Accessibility: aria-label on each badge ("Safe" or "Unsafe"), semantic <article> for cards
- No jQuery, no React, no build step — plain ES6 fetch() only

Output all three files with full content.
