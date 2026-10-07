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
case "$account" in
  perso) acc_rgb="{{acc_rgb.perso}}" ;;
  pro) acc_rgb="{{acc_rgb.pro}}" ;;
  codex) acc_rgb="{{acc_rgb.codex}}" ;;
  *) acc_rgb="{{acc_rgb.other}}" ;;
esac
segments+=("$(printf '\033[1;38;2;%sm● %s\033[0m' "$acc_rgb" "${account:-default}")")
# Model: shown here only while the herdr info panel is closed (it carries the model when open).
model=$(jq -r '.model.display_name // .model.id // empty' <<<"$input" | tr -d '\000-\037')
[[ -n "$model" ]] && segments+=("$(printf '\033[38;2;{{rgb.mauve}}m%s\033[0m' "$model")")
if [[ -n "$dir" ]]; then
  name=${dir/#$HOME/\~}
  segments+=("$(printf '\033[38;2;{{rgb.blue}}m%s\033[0m' "$name")")
  # Same symbols as the herdr agent rows (chrysa.agent-info): ↑ ahead ↓ behind + staged ~ changed ? untracked
  git_line=$(git -C "$dir" status --porcelain=v2 --branch 2>/dev/null | awk '
    /^# branch.head / { b = $3 }
    /^# branch.ab /   { a = substr($3, 2); d = substr($4, 2) }
    /^[12u] /         { if (substr($2,1,1) != ".") s++; if (substr($2,2,1) != ".") c++ }
    /^\? /            { u++ }
    END {
      if (b == "") exit
      out = "{{symbols.branch}} " b
      if (a > 0) out = out " {{symbols.ahead}}" a
      if (d > 0) out = out " {{symbols.behind}}" d
      if (s > 0) out = out " {{symbols.staged}}" s
      if (c > 0) out = out " {{symbols.changed}}" c
      if (u > 0) out = out " {{symbols.untracked}}" u
      print out
    }')
  if [[ -n "$git_line" ]]; then
    if [[ "$git_line" == *" "*" "* ]]; then  # anything after "⑂ branch" means work to do
      git_rgb="{{rgb.yellow}}"
    else
      git_rgb="{{rgb.green}}"; git_line="$git_line {{symbols.done}}"
    fi
    segments+=("$(printf '\033[38;2;%sm%s\033[0m' "$git_rgb" "$git_line")")
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

# Hint for the info panel that replaces this line (herdr only).
[[ -n "${HERDR_ENV:-}" ]] && segments+=("$(printf '\033[2m⌃b ⌃g panel\033[0m')")

out=""
for s in "${segments[@]}"; do out+="${out:+   }$s"; done
printf '%s' "$out"
