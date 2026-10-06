#!/usr/bin/env bash
# Claude Code status line: what THIS session is doing.
# Model, plan limits and tasks live in the herdr info pane (chrysa.agent-info,
# usagebar), so they are deliberately not repeated here.
input=$(cat)
dir=$(jq -r '.workspace.current_dir // .cwd // empty' <<<"$input")
cost=$(jq -r '.cost.total_cost_usd // empty' <<<"$input")

segments=()
# Account = Claude config dir in use (~/.claude-perso -> perso, ~/.claude-pro -> pro).
config_dir=$(readlink -f "${CLAUDE_CONFIG_DIR:-$HOME/.claude}")
account=$(basename "$config_dir" | sed 's/^\.claude-\{0,1\}//')
segments+=("$(printf '\033[1;38;2;249;226;175m● %s\033[0m' "${account:-default}")")
if [[ -n "$dir" ]]; then
  name=${dir/#$HOME/\~}
  segments+=("$(printf '\033[38;2;137;180;250m%s\033[0m' "$name")")
  if branch=$(git -C "$dir" symbolic-ref --short -q HEAD 2>/dev/null); then
    dirty=$(git -C "$dir" status --porcelain 2>/dev/null | wc -l)
    mark=$([[ "$dirty" -gt 0 ]] && printf ' \033[33m±%s\033[0m' "$dirty")
    segments+=("$(printf '\033[38;2;203;166;247m⑂ %s\033[0m%s' "$branch" "$mark")")
  fi
fi

# llmtrim renders: model · context bar · savings · cache. Keep all but the model.
if command -v llmtrim >/dev/null; then
  trimmed=$(llmtrim statusline <<<"$input" 2>/dev/null | perl -pe 's/^.*?   //')
  [[ -n "$trimmed" ]] && segments+=("$trimmed")
fi

# Cost only matters once the plan quota is spent and extra credits are billed
# (flag maintained by chrysa.agent-info from usagebar's limit window).
sid=$(jq -r '.session_id // empty' <<<"$input")
[[ -n "$cost" ]] && [[ -n "$sid" ]] && [[ -f "$HOME/.local/state/chrysa.agent-info/billed/$sid" ]] && segments+=("$(printf '\033[2m$%.2f\033[0m' "$cost")")

# Share this session's footer with the herdr info bar (chrysa.agent-info).
session=$(jq -r '.session_id // empty' <<<"$input")
state="$HOME/.local/state/chrysa.agent-info"
if [[ -n "$session" ]] && [[ "$session" =~ ^[A-Za-z0-9-]+$ ]]; then
  mkdir -p "$state/status"
  usage=$(sed 's/\x1b\[[0-9;]*m//g' <<<"$trimmed" | perl -pe 's/   /\n/g' | jq -R . | jq -sc .)
  jq -n --argjson usage "${usage:-[]}" --arg cost "$cost" --arg pane "${HERDR_PANE_ID:-}" \
    '{usage: $usage, cost: (if $cost == "" then null else ($cost | tonumber) end), pane: $pane, ts: now}' \
    > "$state/status/$session.json.tmp" && mv "$state/status/$session.json.tmp" "$state/status/$session.json"
  # The info bar heartbeats every second while open: then it carries all of this.
  flag="$state/visible/$session"
  if [[ -f "$flag" ]] && [[ $(( $(date +%s) - $(stat -c %Y "$flag") )) -lt 5 ]]; then
    exit 0
  fi
fi

out=""
for s in "${segments[@]}"; do out+="${out:+   }$s"; done
printf '%s' "$out"
