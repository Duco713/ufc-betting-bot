#!/bin/bash
# Odds ophalen -> voorspellingen -> dashboard-data -> push naar GitHub Pages.
# Draait automatisch via een geplande taak in de Claude-app (zie README, "Automatisch verversen").
set -euo pipefail
export PATH="/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin"
cd "$(dirname "$0")/.."
echo "=== $(date '+%Y-%m-%d %H:%M:%S') ==="
PY=.venv/bin/python
$PY -m src.scrapers.bestfightodds
$PY -m src.predict.upcoming --auto-lock | grep -E "Vastgezet|Alles" || true   # vechtdag: vastzetten
$PY -m src.settle > /dev/null                               # uitslagen (data/results/uitslagen.json) afrekenen
$PY -m src.export.site_data
git add docs data/results reports/*.md
if git diff --cached --quiet; then
  echo "Geen wijzigingen"
else
  git commit -q -m "Odds-update $(date '+%Y-%m-%d %H:%M')"
  git push -q
  echo "Gepusht: $(git log --oneline -1)"
fi
