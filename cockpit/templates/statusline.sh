#!/usr/bin/env bash
# Claude Code status line: account, model, folder, git state, then llmtrim's
# context / savings / cache. Plan limits and pay-as-you-go cost come from usagebar
# in herdr's sidebar and limits pane, so they are not repeated here.
input=$(cat)
dir=$(jq -r '.workspace.current_dir // .cwd // empty' <<<"$input")

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
model=$(jq -r '.model.display_name // .model.id // empty' <<<"$input" | tr -d '\000-\037')
[[ -n "$model" ]] && segments+=("$(printf '\033[38;2;{{rgb.mauve}}m%s\033[0m' "$model")")
if [[ -n "$dir" ]]; then
  name=${dir/#$HOME/\~}
  segments+=("$(printf '\033[38;2;{{rgb.blue}}m%s\033[0m' "$name")")
  # Same symbols as the herdr agent rows (chrysa.agent-info): ↑ ahead ↓ behind + staged ~ changed ? untracked
  git_line=$(git --no-optional-locks -C "$dir" status --porcelain=v2 --branch 2>/dev/null | awk '
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

out=""
for s in "${segments[@]}"; do out+="${out:+   }$s"; done
printf '%s' "$out"
