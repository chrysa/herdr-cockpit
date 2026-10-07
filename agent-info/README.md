# agent-info (`chrysa.agent-info`)

Per-agent data for the herdr sidebar, a right-hand info panel, and automatic
agent names. Reads local Claude Code / Codex / opencode session files and the
herdr socket only; no network. Text coming from agents is stripped of control
characters before it is drawn.

## Sidebar tokens (agent rows)

| Token | Example | Source |
|---|---|---|
| `$account` | `perso` | Claude config dir in use (`~/.claude-perso`), `codex`, or the opencode provider |
| `$model` | `opus-5.5` | last model in the session transcript |
| `$git` | `⑂ main ↑2 ~3 ?1` | git state of the agent's folder |
| `$doing` | `▶ Scanning branches…` | the conversation's in-progress task |
| `$todo` | `☐ 2 ✓ 5` | task tally |
| `$subs` | `↳ 2 subagents: explore, security-auditor` | Claude subagents writing in the last 20 s |

Agents are also renamed `<space>-<topic>` (e.g. `padam-av-scheduler-dynamique`);
a name you set by hand is kept.

## Info panel (`prefix+ctrl+g`)

Three views: conversation (default), agents (`a`), espace (`e`):

- **Conversation** (the tab's agent): state and title, then sections
  `Compte` (account in its color, model, quota/context), `Projet` (full local path of the git root, sub-folder if any,
  branch, `↑ à pousser ↓ à tirer + indexés ~ modifiés ? non suivis`, diff stats
  `+12 -3 (4 fichiers)`), `Conso` (each metric colored on its own value: green
  < 50 % used, yellow < 80 %, red beyond; savings and cache the other way round),
  `RTK` (savings recorded by RTK under the project folder: last 24 h and total),
  `Subagents`, `Tâches`; the branch's PR (from `gh-pr`) under Projet; stale work trees (directory gone) counted under Worktrees, `P` runs `git worktree prune`. Cost appears only once usage is billed past the plan
  quota. Keys: `t` tasks, `d` done tasks, `s` subagents, `g` git, `u` usage, `r` RTK.
- **Espace** (`e`): every project of the space selected in herdr — agents
  grouped by git work tree, with branch and git state, open PRs (from the
  `gh-pr` plugin's token, no API call), running services and their URLs, and
  each agent's state.
- **Agents** (the space selected in herdr; `A` for all spaces): grouped
  `‼ bloqués`, `◐ en cours`, `✓ terminés`, `○ en attente`; `1`-`4` fold a group.

`q` closes the panel. Mode, scope and folded groups persist in
`~/.local/state/chrysa.agent-info/panel.json`. Colors and symbols come from the
cockpit palette when `chrysa.cockpit` is set up.

While the panel is open, the Claude Code status line hides itself (it reports
its data to the panel instead).

## Blocked-agent notification

When an agent enters `blocked` (waiting for an approval or an answer), one
desktop notification names it and its space (`notify-send`, herdr's own toast
as fallback). Nothing for other states, and nothing for agents already blocked
when the monitor starts. `chrysa.cockpit` setup disables `jyasha11.in-your-face`,
which this replaces.
