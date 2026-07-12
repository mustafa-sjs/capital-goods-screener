#!/bin/bash
# save_md.sh FUNCTION SYMBOL OUTFILE [INTERVAL]
# Persists the most recent get_market_data(FUNCTION, SYMBOL[, INTERVAL]) result
# from the session transcript into data/raw/OUTFILE via build_viz.py save.
set -e
B=/Users/Mustafa/.claude/plugins/cache/factiq/factiq/0.15.0/scripts/build_viz.py
DIR=/Users/Mustafa/capital-goods-dashboard/data/raw
FUNC=$(echo "$1" | tr 'A-Z' 'a-z')
SYM=$(echo "$2" | tr 'A-Z' 'a-z')
OUT="$3"
case "${4:-}" in
  "")     MATCH="${FUNC}\", \"symbol\": \"${SYM}\"" ;;          # most recent call of func+symbol
  q)      MATCH="${FUNC}\", \"symbol\": \"${SYM}\"}" ;;         # exact: no further params
  *)      MATCH="${FUNC}\", \"symbol\": \"${SYM}\", \"interval\": \"$4\"" ;;
esac
python3 "$B" save --tool get_market_data --match "$MATCH" --out "$DIR/$OUT" >/dev/null && echo "saved $OUT"
