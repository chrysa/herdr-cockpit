#!/usr/bin/env sh
# Open the info pane on the right of the current tab, or close it if already open.
state="$HOME/.local/state/chrysa.agent-info/info-${HERDR_TAB_ID:-default}"
herdr="${HERDR_BIN_PATH:-herdr}"
if [ -f "$state" ] && "$herdr" plugin pane close "$(cat "$state")" >/dev/null 2>&1; then
  rm -f "$state"
  exit 0
fi
mkdir -p "$(dirname "$state")"
"$herdr" plugin pane open --plugin chrysa.agent-info --entrypoint info \
  --placement split --direction right --no-focus \
  | grep -oE '"pane_id":"[^"]*"' | head -1 | cut -d'"' -f4 > "$state"
