#!/bin/bash
# One-command daily refresh: pull latest prices/FX (Yahoo, ~1 min),
# recompute all metrics, re-assemble the dashboard.
set -e
cd "$(dirname "$0")/.."
B=/Users/Mustafa/.claude/plugins/cache/factiq/factiq/0.15.0/scripts/build_viz.py
echo "== 1/3 refreshing prices =="
python3 scripts/refresh_prices.py
echo "== 2/3 recomputing metrics =="
python3 scripts/compute_metrics.py | tail -3
echo "== 3/3 assembling dashboard =="
python3 "$B" assemble --template scripts/dashboard_template.html \
  --data dash=data/computed/dashboard_data.json \
  --out capital_goods_dashboard.html >/dev/null
echo "done — open capital_goods_dashboard.html"
