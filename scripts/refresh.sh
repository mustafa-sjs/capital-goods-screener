#!/bin/bash
# Local daily refresh entry point (used by the launchd agent).
# Full pipeline: prices -> engine -> validation -> DB publish -> HTML.
set -e
cd "$(dirname "$0")/.."
PY=./.venv/bin/python
[ -x "$PY" ] || PY=python3
exec "$PY" scripts/refresh.py --mode daily
