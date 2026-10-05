#!/usr/bin/env python3
"""Right-hand info bar for the conversation running in this tab.

Shows everything about that one conversation in real time: account, model,
folder and git state, context and savings (the Claude Code footer, published
by statusline.sh), plan limits, cost and the full task list. While this pane
is open it heartbeats a flag the status line checks, so the footer hides
instead of repeating the same data.
"""
import glob
import json
import os
import re
import shutil
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import monitor  # noqa: E402

REFRESH_S = 1
SUBAGENT_LIVE_S = 20
SUBAGENT_MAX = 6
STATE = os.path.expanduser("~/.local/state/chrysa.agent-info")
STATUS_DIR = os.path.join(STATE, "status")    # written by statusline.sh
VISIBLE_DIR = os.path.join(STATE, "visible")  # read by statusline.sh
ICON = {"working": "◐ en cours", "blocked": "‼ bloqué", "done": "✓ terminé", "idle": "○ en attente"}
C = {"dim": "\033[2m", "acc": "\033[1;38;2;249;226;175m", "mod": "\033[38;2;203;166;247m",
     "dir": "\033[38;2;137;180;250m", "ok": "\033[38;2;166;227;161m",
     "warn": "\033[38;2;243;139;168m", "yel": "\033[33m", "b": "\033[1m", "r": "\033[0m"}
TASK_ICON = {"in_progress": C["ok"] + "▶", "pending": C["dim"] + "☐", "completed": C["dim"] + "✓"}
CONTROL = re.compile(r"[\x00-\x1f\x7f-\x9f]")
ANSI = re.compile(r"\x1b\[[0-9;?]*[a-zA-Z]")


def safe(text):
    """Drop control characters: titles and tasks come from agents and repos,
    so raw escape sequences must never reach the terminal."""
    return CONTROL.sub("", ANSI.sub("", str(text or "")))


def tasks_for(session_id):
    tasks = []
    for path in [p for d in monitor.claude_dirs() for p in glob.glob(f"{d}/tasks/{session_id}/*.json")]:
        try:
            with open(path) as fh:
                tasks.append(json.load(fh))
        except (OSError, ValueError):
            continue
    order = {"in_progress": 0, "pending": 1, "completed": 2}
    return sorted(tasks, key=lambda t: (order.get(t.get("status"), 3),
                                        int(t["id"]) if str(t.get("id", "")).isdigit() else 0))


def subagents_for(session_id):
    """[(running, type, description)] for subagents spawned by this conversation.

    Claude Code writes them under <config>/projects/<project>/<session>/subagents/
    as agent-<id>.jsonl plus a .meta.json; a transcript touched in the last
    SUBAGENT_LIVE_S seconds is treated as still running.
    """
    found = []
    for meta_path in [p for d in monitor.claude_dirs() for p in glob.glob(f"{d}/projects/*/{session_id}/subagents/*.meta.json")]:
        try:
            with open(meta_path) as fh:
                meta = json.load(fh)
            mtime = os.path.getmtime(meta_path.replace(".meta.json", ".jsonl"))
        except (OSError, ValueError):
            continue
        found.append((time.time() - mtime < SUBAGENT_LIVE_S, mtime,
                      meta.get("agentType") or "agent", meta.get("description") or ""))
    found.sort(key=lambda f: (not f[0], -f[1]))
    return [(running, kind, desc) for running, _, kind, desc in found]


def git_state(cwd):
    try:
        branch = subprocess.run(["git", "-C", cwd, "symbolic-ref", "--short", "-q", "HEAD"],
                                capture_output=True, text=True, timeout=2).stdout.strip()
        if not branch:
            return None, 0
        dirty = subprocess.run(["git", "-C", cwd, "status", "--porcelain"],
                               capture_output=True, text=True, timeout=2).stdout.count("\n")
        return branch, dirty
    except Exception:
        return None, 0


def target_agent():
    """The agent pane of this tab: the focused one if it is an agent, else the first."""
    tab = os.environ.get("HERDR_TAB_ID")
    me = os.environ.get("HERDR_PANE_ID")
    agents = [a for a in monitor.herdr("agent", "list").get("result", {}).get("agents", [])
              if a.get("tab_id") == tab and a.get("pane_id") != me]
    focused = [a for a in agents if a.get("focused")]
    return (focused or agents or [None])[0]


def heartbeat(session_id):
    os.makedirs(VISIBLE_DIR, exist_ok=True)
    path = os.path.join(VISIBLE_DIR, session_id)
    with open(path, "w") as fh:
        fh.write(str(os.getpid()))
    return path


def render(width):
    def cut(text, n=width - 4):
        text = safe(text)
        return text if len(text) <= n else text[:n - 1] + "…"

    agent = target_agent()
    if not agent:
        return [f"{C['dim']}Aucune conversation dans cet onglet{C['r']}"], None
    session = (agent.get("agent_session") or {}).get("value")
    kind = agent.get("agent", "")
    tokens = agent.get("tokens") or {}
    model, account = monitor.agent_info(kind, session, agent.get("cwd"))
    status = agent.get("agent_status", "")
    cwd = agent.get("foreground_cwd") or agent.get("cwd") or ""
    footer = {}
    if session:
        try:
            with open(os.path.join(STATUS_DIR, f"{session}.json")) as fh:
                footer = json.load(fh)
        except (OSError, ValueError):
            pass

    color = C["warn"] if status == "blocked" else C["ok"] if status == "working" else C["dim"]
    lines = [f"{C['b']}{cut(agent.get('terminal_title_stripped') or kind)}{C['r']}",
             f"{color}{ICON.get(status, status)}{C['r']}", ""]

    lines.append(f"{C['acc']}● {safe(account or kind)}{C['r']}  {C['mod']}{safe(model or '?')}{C['r']}")
    if tokens.get("limit"):
        lines.append(f"  {C['dim']}{cut(tokens['limit'])}{C['r']}")
    if tokens.get("context"):
        lines.append(f"  {C['dim']}plan · ctx  {cut(tokens['context'])}{C['r']}")
    lines.append("")

    lines.append(f"{C['dir']}{cut(cwd.replace(monitor.HOME, '~'))}{C['r']}")
    branch, dirty = git_state(cwd) if cwd else (None, 0)
    if branch:
        mark = f" {C['yel']}±{dirty}{C['r']}" if dirty else f" {C['ok']}✓{C['r']}"
        lines.append(f"{C['mod']}⑂ {cut(branch)}{C['r']}{mark}")
    lines.append("")

    for segment in footer.get("usage", []):
        lines.append(cut(segment))
    if footer.get("cost") is not None and monitor.is_billed(tokens):
        lines.append(f"{C['dim']}coût session{C['r']}  ${footer['cost']:.2f}")
    if footer.get("ts"):
        age = int(time.time() - footer["ts"])
        lines.append(f"{C['dim']}màj il y a {age}s{C['r']}")
    lines.append("")

    if session and kind == "claude":
        subs = subagents_for(session)
        if subs:
            live = sum(r for r, _, _ in subs)
            lines.append(f"{C['b']}Subagents{C['r']} {C['dim']}{live} actifs / {len(subs)}{C['r']}")
            for running, sub_kind, desc in subs[:SUBAGENT_MAX]:
                mark = f"{C['ok']}◐" if running else f"{C['dim']}✓"
                lines.append(f"{mark} {cut(sub_kind + ' · ' + desc, width - 4)}{C['r']}")
            if len(subs) > SUBAGENT_MAX:
                lines.append(f"{C['dim']}+{len(subs) - SUBAGENT_MAX} plus anciens{C['r']}")
            lines.append("")
        tasks = tasks_for(session)
        if tasks:
            done = sum(t.get("status") == "completed" for t in tasks)
            lines.append(f"{C['b']}Tâches{C['r']} {C['dim']}{done}/{len(tasks)}{C['r']}")
            room = max(3, shutil.get_terminal_size((40, 40)).lines - len(lines) - 2)
            for t in tasks[:room]:
                text = t.get("activeForm") if t.get("status") == "in_progress" else t.get("subject")
                lines.append(f"{TASK_ICON.get(t.get('status'), '·')} {cut(text, width - 4)}{C['r']}")
            if len(tasks) > room:
                lines.append(f"{C['dim']}+{len(tasks) - room} autres{C['r']}")
    return lines, session


def main():
    flag = None
    sys.stdout.write("\033[?25l")
    try:
        while True:
            width = shutil.get_terminal_size((40, 20)).columns
            try:
                lines, session = render(width)
                if session:
                    new_flag = os.path.join(VISIBLE_DIR, session)
                    if flag and flag != new_flag and os.path.exists(flag):
                        os.remove(flag)
                    flag = heartbeat(session)
            except Exception as exc:  # keep the pane alive across server hiccups
                lines = [f"{C['dim']}herdr indisponible: {safe(exc)}{C['r']}"]
            sys.stdout.write("\033[H\033[2J" + "\n".join(lines))
            sys.stdout.flush()
            time.sleep(REFRESH_S)
    except KeyboardInterrupt:
        pass
    finally:
        if flag and os.path.exists(flag):
            os.remove(flag)
        sys.stdout.write("\033[?25h")


if __name__ == "__main__":
    main()
