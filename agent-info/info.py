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
STATE_ORDER = ("blocked", "working", "done", "idle")
STATE_LABEL = {"blocked": "bloqués", "working": "en cours", "done": "terminés", "idle": "en attente"}
UI = {"mode": "conv", "all_spaces": False, "collapsed": set()}
UI_FILE = os.path.join(STATE, "panel.json")
HELP = {"conv": "a agents · t tâches · d faites · s subagents · g git · u conso · q",
        "agents": "a conversation · A tous les spaces · 1-4 replier · q"}


def load_ui():
    try:
        with open(UI_FILE) as fh:
            data = json.load(fh)
        UI["mode"] = data.get("mode", "conv")
        UI["all_spaces"] = bool(data.get("all_spaces"))
        UI["collapsed"] = set(data.get("collapsed", []))
    except (OSError, ValueError):
        pass


def save_ui():
    os.makedirs(STATE, exist_ok=True)
    with open(UI_FILE, "w") as fh:
        json.dump({"mode": UI["mode"], "all_spaces": UI["all_spaces"],
                   "collapsed": sorted(UI["collapsed"])}, fh)


def cutter(width):
    def cut(text, n=width - 4):
        text = safe(text)
        return text if len(text) <= n else text[:n - 1] + "…"
    return cut


def header(title, width, extra=""):
    """"── Titre ── extra" filling the pane width."""
    label = f"── {title} "
    tail = f" {extra}" if extra else ""
    return f"{C['b']}{label}{C['r']}{C['dim']}{'─' * max(2, width - len(label) - len(tail) - 1)}{tail}{C['r']}"


def state_color(status):
    return {"blocked": C["warn"], "working": C["ok"], "done": C["dir"]}.get(status, C["dim"])


def render(width):
    return render_agents(width) if UI["mode"] == "agents" else render_conversation(width)


def read_footer(session):
    if not session:
        return {}
    try:
        with open(os.path.join(STATUS_DIR, f"{session}.json")) as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def section_account(cut, width, account, kind, model, tokens):
    lines = [header("Compte", width),
             f"{account_color(account)}● {safe(account or kind)}{C['r']}  {C['mod']}{safe(model or '?')}{C['r']}"]
    if tokens.get("context"):
        lines.append(f"{C['dim']}quota · contexte  {cut(tokens['context'], width - 20)}{C['r']}")
    return lines + [""]


def parse_shortstat(text):
    """" 4 files changed, 12 insertions(+), 3 deletions(-)" -> (4, 12, 3)."""
    values = {"file": 0, "insertion": 0, "deletion": 0}
    for part in text.split(","):
        words = part.split()
        if len(words) >= 2 and words[0].isdigit():
            for key in values:
                if words[1].startswith(key):
                    values[key] = int(words[0])
    return values["file"], values["insertion"], values["deletion"]


def git_details(cwd):
    """(branch, counts, shortstat) or None outside a repo.

    counts: ahead, behind, staged, changed, untracked; shortstat: "+12 -3 (4 fichiers)"
    for the working tree against HEAD.
    """
    try:
        out = subprocess.run(["git", "-C", cwd, "status", "--porcelain=v2", "--branch"],
                             capture_output=True, text=True, timeout=3)
        if out.returncode != 0:
            return None
        diff = subprocess.run(["git", "-C", cwd, "diff", "HEAD", "--shortstat"],
                              capture_output=True, text=True, timeout=3).stdout
    except Exception:
        return None
    branch, counts = "?", {"ahead": 0, "behind": 0, "staged": 0, "changed": 0, "untracked": 0}
    for line in out.stdout.splitlines():
        if line.startswith("# branch.head "):
            branch = line.split(" ", 2)[2]
        elif line.startswith("# branch.ab "):
            a, b = line.split()[2:4]
            counts["ahead"], counts["behind"] = int(a), -int(b)
        elif line.startswith(("1 ", "2 ", "u ")):
            xy = line.split()[1]
            counts["staged"] += xy[0] != "."
            counts["changed"] += xy[1] != "."
        elif line.startswith("? "):
            counts["untracked"] += 1
    files, added, removed = parse_shortstat(diff)
    shortstat = ""
    if files:
        plural = "s" if files > 1 else ""
        shortstat = f"+{added} -{removed} ({files} fichier{plural})"
    return safe(branch), counts, shortstat


GIT_LABELS = (("ahead", "↑", "à pousser"), ("behind", "↓", "à tirer"), ("staged", "+", "indexés"),
              ("changed", "~", "modifiés"), ("untracked", "?", "non suivis"))


def git_lines(cut, width, details):
    branch, counts, shortstat = details
    clean = not any(counts.values())
    state = f"  {C['ok']}{SYM['done']} propre{C['r']}" if clean else ""
    lines = [f"{C['mod']}{SYM.get('branch', '⑂')} {cut(branch, width - 4)}{C['r']}{state}"]
    for key, symbol, label in GIT_LABELS:
        if counts[key]:
            color = C["warn"] if key == "behind" else C["yel"]
            lines.append(f"  {color}{symbol}{counts[key]}{C['r']} {C['dim']}{label}{C['r']}")
    if shortstat:
        added, removed, rest = shortstat.split(" ", 2)
        lines.append(f"  {C['ok']}{added}{C['r']} {C['warn']}{removed}{C['r']} {C['dim']}{rest}{C['r']}")
    return lines


def project_root(cwd):
    """Absolute path of the git work tree holding cwd, or None."""
    try:
        out = subprocess.run(["git", "-C", cwd, "rev-parse", "--show-toplevel"],
                             capture_output=True, text=True, timeout=3)
    except Exception:
        return None
    return out.stdout.strip() if out.returncode == 0 and out.stdout.strip() else None


def path_lines(cut, width, cwd):
    """Full local path of the project; the sub-folder too when the agent is not at its root."""
    root = project_root(cwd) if cwd else None
    lines = [f"{C['dir']}{cut(safe(root or cwd), width - 2)}{C['r']}"]
    if root and os.path.realpath(cwd) != os.path.realpath(root):
        lines.append(f"{C['dim']}  └ {cut(os.path.relpath(cwd, root), width - 6)}{C['r']}")
    return lines


def section_project(cut, width, cwd):
    lines = [header("Projet", width)] + path_lines(cut, width, cwd)
    if VIEW["git"] and cwd:
        details = git_details(cwd)
        lines += git_lines(cut, width, details) if details else [f"{C['dim']}pas un dépôt git{C['r']}"]
    return lines + [""]


def level_color(used_ratio):
    """green under 50 % used, yellow under 80 %, red beyond."""
    if used_ratio < 0.5:
        return C["ok"]
    if used_ratio < 0.8:
        return C["yel"]
    return C["warn"]


def percent(text):
    """First "NN%" in text as an int, or None (no regex: input comes from agents)."""
    for word in text.replace("·", " ").split():
        if word.endswith("%") and word[:-1].isdigit():
            return int(word[:-1])
    return None


def color_metric(text):
    """One metric, coloured by its own value.

    Context bar: share of filled blocks. Savings and cache ("✂", "♻"): higher is
    better. Anything else with a percentage (quota windows): higher is worse.
    """
    filled, empty = text.count("▓"), text.count("░")
    if filled + empty:
        return level_color(filled / (filled + empty)) + text + C["r"]
    value = percent(text)
    if value is None:
        return C["dim"] + text + C["r"]
    good_when_high = text.lstrip().startswith(("✂", "♻"))
    return level_color(1 - value / 100 if good_when_high else value / 100) + text + C["r"]


def color_usage(segment):
    """Colour each metric of a segment independently ("◔ 5h·20% · 7d·85%" = two metrics)."""
    parts = safe(segment).split(" · ")
    return f"{C['dim']} · {C['r']}".join(color_metric(part) for part in parts)


def section_usage(cut, width, footer, tokens):
    usage = footer.get("usage", []) if VIEW["usage"] else []
    if not usage:
        return []
    age = int(time.time() - footer["ts"]) if footer.get("ts") else 0
    lines = [header("Conso", width, f"{age}s" if age > 30 else "")]
    if sum(len(safe(u)) for u in usage) + 3 * (len(usage) - 1) <= width - 2:
        lines.append("   ".join(color_usage(u) for u in usage))
    else:
        lines += [color_usage(cut(u)) for u in usage]
    if footer.get("cost") is not None and monitor.is_billed(tokens):
        lines.append(f"{C['warn']}hors quota{C['r']}  ${footer['cost']:.2f}")
    return lines + [""]


def section_subagents(cut, width, session):
    subs = subagents_for(session) if VIEW["subs"] else []
    if not subs:
        return []
    live = sum(r for r, _, _ in subs)
    lines = [header("Subagents", width, f"{live} actifs / {len(subs)}")]
    for running, sub_kind, desc in subs[:SUBAGENT_MAX]:
        mark = f"{C['ok']}{SYM['working']}" if running else f"{C['dim']}{SYM['done']}"
        lines.append(f"{mark} {cut(sub_kind + ' · ' + desc, width - 4)}{C['r']}")
    if len(subs) > SUBAGENT_MAX:
        lines.append(f"{C['dim']}+{len(subs) - SUBAGENT_MAX} plus anciens{C['r']}")
    return lines + [""]


def section_tasks(cut, width, session, used):
    all_tasks = tasks_for(session) if VIEW["tasks"] else []
    if not all_tasks:
        return []
    done = sum(t.get("status") == "completed" for t in all_tasks)
    tasks = all_tasks if VIEW["done"] else [t for t in all_tasks if t.get("status") != "completed"]
    lines = [header("Tâches", width, f"{done}/{len(all_tasks)}")]
    room = max(3, shutil.get_terminal_size((40, 40)).lines - used - 3)
    for t in tasks[:room]:
        text = t.get("activeForm") if t.get("status") == "in_progress" else t.get("subject")
        lines.append(f"{TASK_ICON.get(t.get('status'), '·')} {cut(text, width - 4)}{C['r']}")
    if len(tasks) > room:
        lines.append(f"{C['dim']}+{len(tasks) - room} autres{C['r']}")
    if not tasks:
        lines.append(f"{C['ok']}{SYM['done']} tout est fait{C['r']}")
    return lines


def render_conversation(width):
    cut = cutter(width)
    agent = target_agent()
    if not agent:
        return [f"{C['dim']}Aucune conversation dans cet onglet{C['r']}",
                f"{C['dim']}a : voir les agents du space{C['r']}"], None
    session = monitor.session_for(agent)
    kind = agent.get("agent", "")
    tokens = agent.get("tokens") or {}
    model, account = monitor.agent_info(kind, session, agent.get("cwd"))
    status = agent.get("agent_status", "")
    cwd = agent.get("foreground_cwd") or agent.get("cwd") or ""
    title = cut(agent.get("terminal_title_stripped") or kind, width - 14)
    lines = [f"{state_color(status)}{ICON.get(status, status)}{C['r']}  {C['b']}{title}{C['r']}",
             f"{C['dim']}{safe(agent.get('name') or agent['pane_id'])}{C['r']}", ""]
    lines += section_account(cut, width, account, kind, model, tokens)
    lines += section_project(cut, width, cwd)
    lines += section_usage(cut, width, read_footer(session), tokens)
    if session and kind == "claude":
        lines += section_subagents(cut, width, session)
        lines += section_tasks(cut, width, session, len(lines))
    return lines, session


def focused_workspace():
    for w in monitor.herdr("workspace", "list").get("result", {}).get("workspaces", []):
        if w.get("focused"):
            return w["workspace_id"], w.get("label") or w["workspace_id"]
    return os.environ.get("HERDR_WORKSPACE_ID"), ""


def group_by_state(agents):
    """{state: [agents]} in STATE_ORDER; unknown states count as idle."""
    groups = {state: [] for state in STATE_ORDER}
    for a in agents:
        groups.get(a.get("agent_status"), groups["idle"]).append(a)
    return groups


def agent_lines(cut, width, agent):
    tokens = agent.get("tokens") or {}
    account = tokens.get("account")
    name = agent.get("name") or agent.get("terminal_title_stripped") or agent["pane_id"]
    acc = f" {account_color(account)}{safe(account)}{C['r']}" if account else ""
    lines = [f"  {cut(name, width - 4 - len(account or '') - 1)}{acc}"]
    detail = tokens.get("doing") or tokens.get("git")
    if detail:
        lines.append(f"    {C['dim']}{cut(detail, width - 6)}{C['r']}")
    return lines


def group_lines(cut, width, number, state, members):
    folded = state in UI["collapsed"]
    lines = [f"{state_color(state)}{'▸' if folded else '▾'} {SYM[state]} {STATE_LABEL[state]}{C['r']} "
             f"{C['dim']}{len(members)}  [{number}]{C['r']}"]
    if not folded:
        for agent in members:
            lines += agent_lines(cut, width, agent)
    return lines + [""]


def render_agents(width):
    cut = cutter(width)
    agents = monitor.herdr("agent", "list").get("result", {}).get("agents", [])
    ws_id, label = focused_workspace()
    if not UI["all_spaces"]:
        agents = [a for a in agents if a.get("workspace_id") == ws_id]
    title = "tous les spaces" if UI["all_spaces"] else (label or ws_id)
    lines = [f"{C['b']}Agents · {safe(title)}{C['r']} {C['dim']}({len(agents)}){C['r']}", ""]
    if not agents:
        return lines + [f"{C['dim']}aucun agent{C['r']}"], None
    for number, (state, members) in enumerate(group_by_state(agents).items(), start=1):
        if members:
            lines += group_lines(cut, width, number, state, members)
    return lines, None


def read_key(timeout):
    """One keypress within timeout seconds, or None."""
    ready, _, _ = select.select([sys.stdin], [], [], timeout)
    return sys.stdin.read(1) if ready else None


def main():
    load_ui()
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
            lines = lines[: rows - 2] + ["", f"{C['dim']}{HELP[UI['mode']]}{C['r']}"]
            sys.stdout.write("\033[H\033[2J" + "\n".join(lines))
            sys.stdout.flush()
            key = read_key(REFRESH_S) if interactive else time.sleep(REFRESH_S)
            if key == "q":
                break
            if key == "a":
                UI["mode"] = "agents" if UI["mode"] == "conv" else "conv"
            elif key == "A":
                UI["all_spaces"] = not UI["all_spaces"]
            elif key in ("1", "2", "3", "4") and UI["mode"] == "agents":
                UI["collapsed"] ^= {STATE_ORDER[int(key) - 1]}
            elif key in KEYS and UI["mode"] == "conv":
                VIEW[KEYS[key]] = not VIEW[KEYS[key]]
            else:
                continue
            save_ui()
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
