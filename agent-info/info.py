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
import select
import termios
import time
import tty

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import monitor  # noqa: E402

REFRESH_S = 1
SUBAGENT_LIVE_S = 20
SUBAGENT_MAX = 6
STATE = os.path.expanduser("~/.local/state/chrysa.agent-info")
STATUS_DIR = os.path.join(STATE, "status")    # written by statusline.sh
VISIBLE_DIR = os.path.join(STATE, "visible")  # read by statusline.sh
PALETTE_FILE = os.path.expanduser("~/.local/state/chrysa.cockpit/rendered/palette.json")


def load_palette():
    """Cockpit palette (shared with the sidebar and the status line), or defaults."""
    try:
        with open(PALETTE_FILE) as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {"rgb": {"blue": "137;180;250", "green": "166;227;161", "yellow": "249;226;175",
                        "red": "243;139;168", "mauve": "203;166;247", "overlay": "147;153;178"},
                "accounts": {"perso": "249;226;175", "pro": "137;220;235",
                             "codex": "166;227;161", "other": "147;153;178"},
                "symbols": {"working": "◐", "blocked": "‼", "done": "✓", "idle": "○"}}


PALETTE = load_palette()
SYM = PALETTE["symbols"]
ICON = {"working": f"{SYM['working']} en cours", "blocked": f"{SYM['blocked']} bloqué",
        "done": f"{SYM['done']} terminé", "idle": f"{SYM['idle']} en attente"}


def fg(rgb, bold=False):
    return f"\033[{'1;' if bold else ''}38;2;{rgb}m"


C = {"dim": "\033[2m", "mod": fg(PALETTE["rgb"]["mauve"]), "dir": fg(PALETTE["rgb"]["blue"]),
     "ok": fg(PALETTE["rgb"]["green"]), "warn": fg(PALETTE["rgb"]["red"]),
     "yel": fg(PALETTE["rgb"]["yellow"]), "b": "\033[1m", "r": "\033[0m"}
TASK_ICON = {"in_progress": C["ok"] + "▶", "pending": C["dim"] + "☐", "completed": C["dim"] + SYM["done"]}


def account_color(account):
    return fg(PALETTE["accounts"].get(account, PALETTE["accounts"]["other"]), bold=True)
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


VIEW = {"tasks": True, "done": False, "subs": True, "git": True, "usage": True}
KEYS = {"t": "tasks", "d": "done", "s": "subs", "g": "git", "u": "usage"}
HELP = "t tâches · d faites · s subagents · g git · u conso · q fermer"


def render(width):
    def cut(text, n=width - 4):
        text = safe(text)
        return text if len(text) <= n else text[:n - 1] + "…"

    agent = target_agent()
    if not agent:
        return [f"{C['dim']}Aucune conversation dans cet onglet{C['r']}"], None
    session = monitor.session_for(agent)
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

    lines.append(f"{account_color(account)}● {safe(account or kind)}{C['r']}  {C['mod']}{safe(model or '?')}{C['r']}")
    if tokens.get("limit"):
        lines.append(f"  {C['dim']}{cut(tokens['limit'])}{C['r']}")
    if tokens.get("context"):
        lines.append(f"  {C['dim']}plan · ctx  {cut(tokens['context'])}{C['r']}")
    lines.append("")

    lines.append(f"{C['dir']}{cut(cwd.replace(monitor.HOME, '~'))}{C['r']}")
    git = monitor.git_summary(cwd) if VIEW["git"] else None
    if git:
        color = C["ok"] if git.endswith("✓") else C["yel"]
        lines.append(f"{color}{cut(git)}{C['r']}")
        lines.append(f"{C['dim']}↑ à pousser ↓ à tirer + indexé ~ modifié ? non suivi{C['r']}")
    lines.append("")

    for segment in footer.get("usage", []) if VIEW["usage"] else []:
        lines.append(cut(segment))
    if footer.get("cost") is not None and monitor.is_billed(tokens):
        lines.append(f"{C['dim']}coût session{C['r']}  ${footer['cost']:.2f}")
    if footer.get("ts"):
        age = int(time.time() - footer["ts"])
        lines.append(f"{C['dim']}màj il y a {age}s{C['r']}")
    lines.append("")

    if session and kind == "claude":
        subs = subagents_for(session) if VIEW["subs"] else []
        if subs:
            live = sum(r for r, _, _ in subs)
            lines.append(f"{C['b']}Subagents{C['r']} {C['dim']}{live} actifs / {len(subs)}{C['r']}")
            for running, sub_kind, desc in subs[:SUBAGENT_MAX]:
                mark = f"{C['ok']}◐" if running else f"{C['dim']}✓"
                lines.append(f"{mark} {cut(sub_kind + ' · ' + desc, width - 4)}{C['r']}")
            if len(subs) > SUBAGENT_MAX:
                lines.append(f"{C['dim']}+{len(subs) - SUBAGENT_MAX} plus anciens{C['r']}")
            lines.append("")
        tasks = tasks_for(session) if VIEW["tasks"] else []
        if not VIEW["done"]:
            done_count = sum(t.get("status") == "completed" for t in tasks)
            total = len(tasks)
            tasks = [t for t in tasks if t.get("status") != "completed"]
        if tasks or (VIEW["tasks"] and not VIEW["done"] and done_count):
            done = done_count if not VIEW["done"] else sum(t.get("status") == "completed" for t in tasks)
            total = total if not VIEW["done"] else len(tasks)
            lines.append(f"{C['b']}Tâches{C['r']} {C['dim']}{done}/{total}{C['r']}")
            room = max(3, shutil.get_terminal_size((40, 40)).lines - len(lines) - 2)
            for t in tasks[:room]:
                text = t.get("activeForm") if t.get("status") == "in_progress" else t.get("subject")
                lines.append(f"{TASK_ICON.get(t.get('status'), '·')} {cut(text, width - 4)}{C['r']}")
            if len(tasks) > room:
                lines.append(f"{C['dim']}+{len(tasks) - room} autres{C['r']}")
    return lines, session


def read_key(timeout):
    """One keypress within timeout seconds, or None."""
    ready, _, _ = select.select([sys.stdin], [], [], timeout)
    return sys.stdin.read(1) if ready else None


def main():
    flag = None
    interactive = sys.stdin.isatty()
    saved = termios.tcgetattr(sys.stdin) if interactive else None
    if interactive:
        tty.setcbreak(sys.stdin)
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
            rows = shutil.get_terminal_size((40, 20)).lines
            lines = lines[: rows - 2] + ["", f"{C['dim']}{HELP}{C['r']}"]
            sys.stdout.write("\033[H\033[2J" + "\n".join(lines))
            sys.stdout.flush()
            key = read_key(REFRESH_S) if interactive else time.sleep(REFRESH_S)
            if key == "q":
                break
            if key in KEYS:
                VIEW[KEYS[key]] = not VIEW[KEYS[key]]
    except KeyboardInterrupt:
        pass
    finally:
        if saved:
            termios.tcsetattr(sys.stdin, termios.TCSADRAIN, saved)
        if flag and os.path.exists(flag):
            os.remove(flag)
        sys.stdout.write("\033[?25h")


if __name__ == "__main__":
    main()
