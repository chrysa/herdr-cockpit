"""Housekeeping the agent-info daemon does on its own, each action announced by a
desktop notification.

Idle agents (AGENT_INFO_TIDY_HOURS, default 24, 0 = off): a Claude agent idle that
long, not in the focused tab, with no subtask listed and an empty prompt, is quit
with Ctrl+C twice. Its pane goes back to the shell, so herdr does not resume it on
restart; the conversation stays (`claude --resume <id>`), and every closed agent is
logged in CLOSED (one JSON line each).

Tabs (AGENT_INFO_SORT_TABS=0 turns it off): a tab whose only pane is an agent
started in a git work tree below its space's folder (chrysa/prism-ai-lint in the
space of chrysa/) moves to that repo's space, a new one when there is none (the
daemon then sorts it under its parent). Never the focused tab, nor an agent waiting
on you.
"""

import json
import os
import re
import time

TIDY_HOURS = float(os.environ.get("AGENT_INFO_TIDY_HOURS", "24") or 0)
SORT_TABS = os.environ.get("AGENT_INFO_SORT_TABS", "1") != "0"
PROMPT = "❯"  # Claude Code's input line
ANSI = re.compile(r"\x1b\[[0-9;]*m")
GHOST = re.compile(r"\x1b\[2m.*?(?:\x1b\[0m|$)")  # dim text after ❯: Claude Code's suggested prompt, not a draft
PLUGINS = os.path.expanduser("~/.config/herdr/plugins")  # plugin panes (agent-panel) live here
RETRY_S = 3600  # a pane left alone (a draft in its prompt, a failed move) is tried again after this
AGENTS = ("claude", "codex", "opencode")


def inside(path, parent):
    return bool(path and parent) and path != parent and path.startswith(parent.rstrip("/") + "/")


def plugin_pane(pane):
    return inside(os.path.normpath(pane.get("cwd") or ""), PLUGINS)


# ── idle agents ───────────────────────────────────────────────────────────────

def idle_to_close(agents, since, subs, focused_tab, now, hours=TIDY_HOURS):
    """Claude agents idle for `hours`: not in the focused tab, no subtask listed.

    since: pane_id -> [status, seq, first seen]; subs: pane_id -> subtask statuses.
    """
    if hours <= 0:
        return []
    found = []
    for agent in agents:
        entry = since.get(agent.get("pane_id"))
        if (agent.get("agent") == "claude" and agent.get("agent_status") == "idle"
                and not agent.get("focused") and agent.get("tab_id") != focused_tab
                and entry and entry[0] == "idle" and now - entry[2] >= hours * 3600
                and not subs.get(agent.get("pane_id"))):
            found.append(agent)
    return found


def prompt_empty(screen):
    """True when Claude Code's last input line ("❯", read with ANSI styles) holds no
    draft; a dim suggestion there does not count."""
    prompts = [line for line in screen.splitlines() if ANSI.sub("", line).lstrip(" │").startswith(PROMPT)]
    if not prompts:
        return False
    after = prompts[-1].split(PROMPT, 1)[1]
    return not ANSI.sub("", GHOST.sub("", after)).replace("\xa0", " ").strip(" │\r")


def runs_claude(process_info):
    procs = ((process_info.get("result") or {}).get("process_info") or {}).get("foreground_processes") or []
    return any(p.get("name") == "claude" for p in procs)


def close_idle(agent, herdr, herdr_text, wait=None):
    """Quit one idle Claude agent if its prompt is empty; True once it has quit."""
    wait = wait or time.sleep
    pane = agent["pane_id"]
    if not prompt_empty(herdr_text("pane", "read", pane, "--source", "visible", "--lines", "60", "--format", "ansi")):
        return False  # a draft is waiting: leave it
    herdr("pane", "send-keys", pane, "ctrl+c", "ctrl+c")
    for _ in range(6):
        wait(0.5)
        if not runs_claude(herdr("pane", "process-info", "--pane", pane)):
            return True
    return False


def log_closed(path, agent, space, name, now):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    entry = {"time": time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime(now)), "pane": agent.get("pane_id"),
             "space": space, "name": name, "cwd": agent.get("cwd"),
             "session": (agent.get("agent_session") or {}).get("value")}
    with open(path, "a") as fh:
        fh.write(json.dumps(entry, ensure_ascii=False) + "\n")


# ── tabs in their repo's space ────────────────────────────────────────────────

def repo_root(path, stop):
    """The git work tree holding path, when it lies strictly below stop."""
    current = os.path.normpath(path or "")
    stop = os.path.normpath(stop or "/")
    while inside(current, stop):
        if os.path.exists(os.path.join(current, ".git")):
            return current
        current = os.path.dirname(current)
    return None


def tab_moves(agents, panes, folders, focused_tab, root_of=None):
    """[(pane_id, target workspace_id or None for a new space, repo root)].

    folders: workspace_id -> its folder (monitor.space_folders).
    """
    root_of = root_of or repo_root
    by_tab = {}
    for pane in panes:
        if not plugin_pane(pane):
            by_tab.setdefault(pane.get("tab_id"), []).append(pane)
    agent_of = {a.get("pane_id"): a for a in agents}
    space_of_folder = {folder: ws for ws, folder in folders.items() if folder}
    moves = []
    for tab, members in by_tab.items():
        if tab == focused_tab or len(members) != 1:
            continue
        agent = agent_of.get(members[0].get("pane_id"))
        if not agent or agent.get("agent") not in AGENTS or agent.get("agent_status") == "blocked":
            continue
        folder = folders.get(agent.get("workspace_id"))
        root = root_of(members[0].get("foreground_cwd") or members[0].get("cwd"), folder)
        if root:
            moves.append((agent["pane_id"], space_of_folder.get(root), root))
    return moves


def move_tab(pane, target, root, herdr):
    """Move the pane (its tab's only one) to target, or to a new space named after root."""
    where = ["--workspace", target, "--new-tab"] if target else ["--new-workspace", "--label", os.path.basename(root)]
    herdr("pane", "move", pane, *where, "--no-focus")


# ── one pass ──────────────────────────────────────────────────────────────────

def run(agents, panes, workspaces, folders, since, subs, names, state, now, herdr, herdr_text, notify, closed_log):
    """Both passes; a pane is tried at most once per RETRY_S (state["tidied"])."""
    focused_tab = next((w.get("active_tab_id") for w in workspaces if w.get("focused")), None)
    labels = {w.get("workspace_id"): w.get("label") or "" for w in workspaces}
    tried = state.setdefault("tidied", {})  # pane_id -> when last tried

    def fresh(pane):
        if now - tried.get(pane, -RETRY_S) < RETRY_S:
            return False
        tried[pane] = now
        return True

    closed = []
    for agent in idle_to_close(agents, since, subs, focused_tab, now):
        if not fresh(agent["pane_id"]):
            continue
        try:
            if close_idle(agent, herdr, herdr_text):
                name = names.get(agent["pane_id"]) or labels.get(agent.get("workspace_id"))
                log_closed(closed_log, agent, labels.get(agent.get("workspace_id")), name, now)
                closed.append(name or agent["pane_id"])
        except (RuntimeError, OSError, ValueError):
            continue
    if closed:
        notify(f"herdr · {len(closed)} agent(s) inactif(s) fermé(s)",
               f"{', '.join(closed[:4])}{' …' if len(closed) > 4 else ''} — reprise : claude --resume")
    moved = []
    for pane, target, root in (tab_moves(agents, panes, folders, focused_tab) if SORT_TABS else []):
        if not fresh(pane):
            continue
        try:
            move_tab(pane, target, root, herdr)
            moved.append(f"{names.get(pane) or pane} → {os.path.basename(root)}")
        except (RuntimeError, OSError, ValueError):
            continue
    if moved:
        notify(f"herdr · {len(moved)} onglet(s) rangé(s)", "\n".join(moved[:4]))
    live = {a.get("pane_id") for a in agents}
    for gone in set(tried) - live:
        del tried[gone]
    return closed, moved
