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
import sqlite3
import subprocess
import sys
import tempfile
import select
import termios
import time
from datetime import datetime, timedelta, timezone
import tty

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import monitor  # noqa: E402
import services  # noqa: E402

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


def ttl_cache(seconds):
    """Memoise a one-argument function for `seconds` (git calls cost ~0.1-0.2 s each)."""
    def wrap(fn):
        store = {}

        def cached(arg):
            hit = store.get(arg)
            if hit and time.monotonic() - hit[0] < seconds:
                return hit[1]
            value = fn(arg)
            store[arg] = (time.monotonic(), value)
            return value
        cached.cache = store
        return cached
    return wrap


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
    cwd = safe_dir(cwd)
    if not cwd:
        return None, 0
    try:
        branch = subprocess.run(["git", "--no-optional-locks", "-C", cwd, "symbolic-ref", "--short", "-q", "HEAD"],
                                capture_output=True, text=True, timeout=2).stdout.strip()
        if not branch:
            return None, 0
        dirty = subprocess.run(["git", "--no-optional-locks", "-C", cwd, "status", "--porcelain"],
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


VIEW = {"tasks": True, "done": False, "subs": True, "git": True, "usage": True, "rtk": True, "services": True}
KEYS = {"t": "tasks", "d": "done", "s": "subs", "g": "git", "u": "usage", "r": "rtk", "w": "services"}
STATE_ORDER = ("blocked", "working", "done", "idle")
STATE_LABEL = {"blocked": "bloqués", "working": "en cours", "done": "terminés", "idle": "en attente"}
UI = {"mode": "conv", "all_spaces": False, "collapsed": set()}
UI_FILE = os.path.join(STATE, "panel.json")
HELP = {"conv": "a agents · e espace · t tâches · d faites · s subagents · g git · u conso · r rtk · w services · q",
        "agents": "a conversation · e espace · A tous les spaces · 1-4 replier · q",
        "space": "e conversation · a agents · q"}


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
    if UI["mode"] == "agents":
        return render_agents(width)
    if UI["mode"] == "space":
        return render_space(width)
    return render_conversation(width)


def projects_of(agents):
    """{project root: [agents]}: each agent under the git work tree it works in (or its folder)."""
    projects = {}
    for agent in agents:
        where = safe_dir(agent.get("foreground_cwd") or agent.get("cwd") or "")
        if not where:
            continue
        projects.setdefault(project_root(where) or where, []).append(agent)
    return projects


@ttl_cache(5)
def cached_git_summary(root):
    return monitor.git_summary(root)


def services_summary(cut, width, root):
    """"● 5 services  http://… http://…" for a git project, or nothing."""
    if not project_root(root):
        return []
    boxes, procs = services.services(root)
    count = sum(b["state"] == "running" for b in boxes) + len(procs)
    if not count:
        return []
    urls = [u for b in boxes if b["state"] == "running" for u in b["urls"]] + [p["url"] for p in procs]
    shown = f"  {C['dir']}{cut(' '.join(urls[:2]), width - 18)}{C['r']}" if urls else ""
    plural = "s" if count > 1 else ""
    return [f"  {C['ok']}● {count} service{plural}{C['r']}{shown}"]


def project_block(cut, width, root, members):
    """One project of the space: name, git, PRs, running services, agents."""
    name = os.path.basename(root) or root
    lines = [f"{C['b']}■ {cut(name, width - 4)}{C['r']}"]
    git = cached_git_summary(root)
    if git:
        lines.append(f"  {C['ok'] if git.endswith('✓') else C['yel']}{cut(git, width - 4)}{C['r']}")
    prs = sorted({safe((a.get("tokens") or {}).get("pr", "")) for a in members} - {""})
    if prs:
        lines.append(f"  {C['dir']}PR {cut(' '.join(prs), width - 7)}{C['r']}")
    lines += services_summary(cut, width, root)
    for agent in members:
        status = agent.get("agent_status", "")
        who = safe(agent.get("name") or agent.get("terminal_title_stripped") or agent["pane_id"])
        lines.append(f"  {state_color(status)}{SYM.get(status, '·')}{C['r']} {cut(who, width - 6)}")
    return lines + [""]


def render_space(width):
    cut = cutter(width)
    agents = monitor.herdr("agent", "list").get("result", {}).get("agents", [])
    ws_id, label = focused_workspace()
    agents = [a for a in agents if a.get("workspace_id") == ws_id]
    projects = projects_of(agents)
    lines = [f"{C['b']}Espace · {safe(label or ws_id)}{C['r']} "
             f"{C['dim']}({len(projects)} projet{'s' if len(projects) > 1 else ''}, {len(agents)} agents){C['r']}", ""]
    if not projects:
        return lines + [f"{C['dim']}aucun agent dans ce space{C['r']}"], None
    for root in sorted(projects, key=lambda r: (-len(projects[r]), r)):
        lines += project_block(cut, width, root, projects[root])
    return lines, None


ALLOWED_ROOTS = (os.path.normpath(os.path.expanduser("~")),)


def safe_dir(path):
    """Absolute, normalised, existing directory, or "".

    Paths come from files other processes write (status line state) and end
    up as `git -C <path>`: only absolute paths under the home directory,
    without control characters, are accepted (so nothing git could
    read as an option, and no probing of the rest of the filesystem).
    """
    if not isinstance(path, str) or not path.startswith("/") or CONTROL.search(path):
        return ""
    normalised = os.path.normpath(path)
    allowed = next((base for base in ALLOWED_ROOTS
                    if normalised == base or normalised.startswith(base + os.sep)), None)
    if allowed is None:
        return ""
    rel = os.path.relpath(normalised, allowed)
    candidate = allowed if rel == "." else os.path.join(allowed, rel)
    return candidate if os.path.isdir(candidate) else ""


def conversation_dir(agent, footer):
    """Where the conversation actually works.

    herdr reports the pane's shell cwd (often where the pane was opened, e.g.
    ~); Claude Code's status line reports the session's real working directory,
    so it wins when present and still exists.
    """
    return (safe_dir(footer.get("dir"))
            or safe_dir(agent.get("foreground_cwd"))
            or safe_dir(agent.get("cwd")))


def read_footer(session):
    if not session:
        return {}
    try:
        with open(os.path.join(STATUS_DIR, f"{session}.json")) as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def plan_line(tokens):
    """usagebar packs "<window> <left%> · <context%>" into $context: label both parts."""
    raw = safe(tokens.get("context") or "")
    if not raw:
        return ""
    window, _, context = raw.partition(" · ")
    parts = []
    if window:
        parts.append(f"{C['dim']}quota restant{C['r']} {window}")
    if context:
        parts.append(f"{C['dim']}contexte{C['r']} {context}")
    return "   ".join(parts)


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
    """(branch, counts, shortstat) or None outside a repo (or for an unsafe path).

    counts: ahead, behind, staged, changed, untracked; shortstat: "+12 -3 (4 fichiers)"
    for the working tree against HEAD.
    """
    cwd = safe_dir(cwd)
    if not cwd:
        return None
    try:
        out = subprocess.run(["git", "--no-optional-locks", "-C", cwd, "status", "--porcelain=v2", "--branch"],
                             capture_output=True, text=True, timeout=3)
        if out.returncode != 0:
            return None
        diff = subprocess.run(["git", "--no-optional-locks", "-C", cwd, "diff", "HEAD", "--shortstat"],
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
    parts = [f"{C['mod']}{SYM.get('branch', '⑂')} {cut(branch, width // 2)}{C['r']}"]
    if clean:
        parts.append(f"{C['ok']}{SYM['done']} propre{C['r']}")
    for key, symbol, label in GIT_LABELS:
        if counts[key]:
            color = C["warn"] if key == "behind" else C["yel"]
            parts.append(f"{color}{symbol}{counts[key]}{C['r']} {C['dim']}{label}{C['r']}")
    if shortstat:
        added, removed, rest = shortstat.split(" ", 2)
        parts.append(f"{C['ok']}{added}{C['r']} {C['warn']}{removed}{C['r']} {C['dim']}{rest}{C['r']}")
    joined = "  ".join(parts)
    if len(ANSI.sub("", joined)) <= width - 1:
        return [joined]
    return [parts[0]] + [f"  {part}" for part in parts[1:]]


@ttl_cache(60)
def project_root(cwd):
    """Absolute path of the git work tree holding cwd, or None."""
    cwd = safe_dir(cwd)
    if not cwd:
        return None
    try:
        out = subprocess.run(["git", "--no-optional-locks", "-C", cwd, "rev-parse", "--show-toplevel"],
                             capture_output=True, text=True, timeout=3)
    except Exception:
        return None
    return out.stdout.strip() if out.returncode == 0 and out.stdout.strip() else None


def wrap_path(path, width):
    """Full path over several lines, broken after a "/" when possible, never truncated."""
    room = max(10, width - 2)
    lines = []
    while len(path) > room:
        cut_at = path.rfind("/", 0, room) + 1 or room
        lines.append(path[:cut_at])
        path = path[cut_at:]
    return lines + [path]


def remote_url(cwd):
    """Browsable URL of the repository's `origin` remote (local git only, no API call)."""
    cwd = safe_dir(cwd)
    if not cwd:
        return None
    try:
        out = subprocess.run(["git", "--no-optional-locks", "-C", cwd, "remote", "get-url", "origin"],
                             capture_output=True, text=True, timeout=3)
    except Exception:
        return None
    return browsable(out.stdout.strip()) if out.returncode == 0 else None


def browsable(remote):
    """git@github.com:owner/repo.git or https://…/owner/repo.git -> https://github.com/owner/repo."""
    remote = safe(remote).removesuffix(".git")
    if remote.startswith("git@") and ":" in remote:
        host, _, repo = remote[len("git@"):].partition(":")
        return f"https://{host}/{repo}"
    if remote.startswith(("ssh://", "git://")):
        rest = remote.split("://", 1)[1].split("@", 1)[-1]
        host, _, repo = rest.partition("/")
        return f"https://{host.split(':')[0]}/{repo}"
    if remote.startswith("https://"):
        rest = remote[len("https://"):]
        host, _, path = rest.partition("/")
        return f"https://{host.rsplit('@', 1)[-1]}/{path}"  # never show embedded credentials
    return remote or None


def path_lines(cut, width, cwd):
    """The conversation's current directory, in full; the git root it belongs to as a note."""
    lines = [f"{C['dir']}{part}{C['r']}" for part in wrap_path(safe(cwd), width)]
    root = project_root(cwd) if cwd else None
    if root and os.path.realpath(cwd) != os.path.realpath(root):
        lines.append(f"{C['dim']}  dépôt {cut(os.path.basename(root), width - 10)}{C['r']}")
    remote = remote_url(cwd) if root else None
    if remote:
        lines.append(f"{C['dir']}  ↗ {cut(remote, width - 6)}{C['r']}")
    return lines


def section_project(cut, width, cwd, pr=""):
    lines = [header("Projet", width)] + path_lines(cut, width, cwd)
    if VIEW["git"] and cwd:
        details = git_details(cwd)
        lines += git_lines(cut, width, details) if details else [f"{C['dim']}pas un dépôt git{C['r']}"]
    if pr:
        lines.append(f"{C['dir']}PR {cut(safe(pr), width - 4)}{C['r']}")
    return lines + [""]


RTK_DB = os.path.expanduser("~/.local/share/rtk/history.db")


def rtk_stats(root, since=None, db=RTK_DB):
    """(commands, input_tokens, saved_tokens) RTK recorded under root, read-only."""
    if not root or not os.path.exists(db):
        return None
    sql = ("SELECT COUNT(*), COALESCE(SUM(input_tokens), 0), COALESCE(SUM(saved_tokens), 0) "
           "FROM commands WHERE (project_path = ? OR substr(project_path, 1, ?) = ?)")
    params = [root, len(root) + 1, root + os.sep]
    if since:
        sql += " AND timestamp >= ?"
        params.append(since)
    try:
        conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=2)
        try:
            return conn.execute(sql, params).fetchone()
        finally:
            conn.close()
    except sqlite3.Error:
        return None


def human(n):
    for unit, size in (("M", 1_000_000), ("K", 1_000)):
        if n >= size:
            return f"{n / size:.1f}{unit}"
    return str(n)


def rtk_line(label, stats):
    commands, sent, saved = stats
    rate = saved / sent if sent else 0
    return (f"{C['dim']}{label}{C['r']} {level_color(1 - rate)}{rate:.0%}{C['r']} "
            f"{C['dim']}({human(saved)} économisés, {commands} cmd){C['r']}")


STATE_STYLE = {"running": "ok", "restarting": "yel", "paused": "yel", "created": "dim",
               "exited": "warn", "dead": "warn"}


PRUNABLE = {}  # repo root -> work trees whose directory is gone (filled by worktrees())


def prune_worktrees(cwd):
    """`git worktree prune`: drops only the records of work trees whose directory no longer exists."""
    root = project_root(cwd)
    if not root:
        return False
    out = subprocess.run(["git", "-C", root, "worktree", "prune"], capture_output=True, text=True, timeout=10)
    PRUNABLE.pop(os.path.realpath(root), None)
    return out.returncode == 0


def worktrees(cwd):
    """[(path, branch, is_current)] for the git work trees of cwd's repository."""
    cwd = safe_dir(cwd)
    if not cwd:
        return []
    try:
        out = subprocess.run(["git", "--no-optional-locks", "-C", cwd, "worktree", "list", "--porcelain"],
                             capture_output=True, text=True, timeout=3)
    except Exception:
        return []
    if out.returncode != 0:
        return []
    here = os.path.realpath(project_root(cwd) or cwd)
    records = parse_worktree_list(out.stdout)
    PRUNABLE[here] = sum(r["prunable"] for r in records)
    return [(safe(r["path"]), safe(r["branch"]), os.path.realpath(r["path"]) == here)
            for r in records if not r["prunable"]]


def parse_worktree_list(porcelain):
    """`git worktree list --porcelain` -> [{path, branch, prunable}]."""
    records, current = [], {}
    for line in porcelain.splitlines() + [""]:
        if not line:
            if current.get("path"):
                records.append({"path": current["path"], "branch": current.get("branch", ""),
                                "prunable": current.get("prunable", False)})
            current = {}
        elif line.startswith("worktree "):
            current["path"] = line[len("worktree "):]
        elif line.startswith("branch "):
            current["branch"] = line[len("branch "):].removeprefix("refs/heads/")
        elif line == "detached":
            current["branch"] = "(détaché)"
        elif line.startswith("prunable"):
            current["prunable"] = True
    return records


def agents_by_worktree(trees, agents, labels):
    """{worktree path: ["agent-name (space)", ...]} using each agent's directory."""
    by_tree = {path: [] for path, _, _ in trees}
    for agent in agents:
        where = safe_dir(agent.get("foreground_cwd") or agent.get("cwd") or "")
        for path in sorted(by_tree, key=len, reverse=True):
            if where and (where == path or where.startswith(path + os.sep)):
                name = safe(agent.get("name") or agent.get("pane_id", "?"))
                space = safe(labels.get(agent.get("workspace_id"), ""))
                by_tree[path].append(f"{name} ({space})" if space and not name.startswith(space) else name)
                break
    return by_tree


SCRATCH_ROOT = os.path.realpath(tempfile.gettempdir())


def is_scratch(path):
    """Throw-away work trees (agent scratch copies under the system temp dir); read-only check."""
    return os.path.realpath(path).startswith(SCRATCH_ROOT + os.sep)


def worktree_lines(cut, width, path, branch, current, workers):
    mark, color = ("▶", C["ok"]) if current else (" ", C["dim"])
    lines = [f"{color}{mark} {cut(branch or '?', width - 4)}{C['r']}",
             f"{C['dim']}  {cut(path.replace(monitor.HOME, '~'), width - 4)}{C['r']}"]
    return lines + [f"  {C['mod']}◐ {cut(who, width - 6)}{C['r']}" for who in workers]


def section_worktrees(cut, width, cwd):
    """Every work tree of the repository, the current one highlighted (only when there are several)."""
    if not VIEW["git"]:
        return []
    trees = worktrees(cwd)
    stale = PRUNABLE.get(os.path.realpath(project_root(cwd) or cwd), 0)
    if len(trees) < 2 and not stale:
        return []
    try:
        agents = monitor.herdr("agent", "list").get("result", {}).get("agents", [])
        labels = {w["workspace_id"]: w.get("label") for w in
                  monitor.herdr("workspace", "list").get("result", {}).get("workspaces", [])}
    except Exception:
        agents, labels = [], {}
    busy = agents_by_worktree(trees, agents, labels)
    lines = [header("Worktrees", width, str(len(trees)))]
    shown = [t for t in trees if not (is_scratch(t[0]) and not t[2] and not busy.get(t[0]))]
    hidden = len(trees) - len(shown)
    for path, branch, current in shown:
        lines += worktree_lines(cut, width, path, branch, current, busy.get(path, []))
    if hidden:
        lines.append(f"{C['dim']}  +{hidden} temporaire{'s' if hidden > 1 else ''}{C['r']}")
    if stale:
        lines.append(f"{C['yel']}  {stale} obsolète{'s' if stale > 1 else ''} (dossier supprimé){C['r']}"
                     f" {C['dim']}· P pour nettoyer{C['r']}")
    return lines + [""]


def service_rows(boxes, procs):
    """(style, name, status, urls) rows: running containers first, then processes."""
    order = {"running": 0, "restarting": 1, "paused": 2}
    rows = []
    for box in sorted(boxes, key=lambda b: (order.get(b["state"], 9), b["name"])):
        health = "" if box["health"] in ("none", "") else f" {safe(box['health'])}"
        rows.append((STATE_STYLE.get(box["state"], "dim"), safe(box["name"]),
                     safe(box["status"]) + health, box["urls"]))
    for proc in procs:
        rows.append(("ok", safe(proc["name"]), f"pid {proc['pid']}", [proc["url"]]))
    return rows


def service_lines(cut, width, row, name_w, status_w):
    """One aligned row; the first URL on the same line when it fits."""
    style, name, status, urls = row
    faded = C["dim"] if style in ("dim", "warn") else ""
    line = (f"{C[style]}●{C['r']} {faded}{cut(name, name_w).ljust(name_w)}{C['r']}"
            f"  {C['dim']}{status[:status_w].ljust(status_w)}{C['r']}")
    first = urls[0] if urls else ""
    if first and len(first) <= width - 6 - name_w - status_w:
        lines = [f"{line}  {C['dir']}{first}{C['r']}"]
    else:
        lines = [line] + ([f"    {C['dir']}{cut(first, width - 6)}{C['r']}"] if first else [])
    return lines + [f"    {C['dir']}{cut(extra, width - 6)}{C['r']}" for extra in urls[1:]]


def section_services(cut, width, cwd):
    """Containers and listening processes of this project, with their URLs."""
    if not VIEW["services"]:
        return []
    # Only the current project: a git work tree. Outside one (e.g. ~ or a folder of
    # projects) there is no single project to attribute services to, so show none.
    root = project_root(cwd)
    if not root:
        return []
    boxes, procs = services.services(root)
    if not boxes and not procs:
        return []
    running = sum(b["state"] == "running" for b in boxes) + len(procs)
    lines = [header("Services", width, f"{running} actifs")]
    rows = service_rows(boxes, procs)
    name_w = min(max(len(r[1]) for r in rows), max(8, width // 3))
    status_w = min(max(len(r[2]) for r in rows), 18)
    for row in rows:
        lines += service_lines(cut, width, row, name_w, status_w)
    return lines + [""]


def section_rtk(width, cwd):
    """RTK savings for this project folder: last 24 h and since the beginning."""
    if not VIEW["rtk"]:
        return []
    root = project_root(cwd) or cwd
    total = rtk_stats(root)
    if not total or not total[0]:
        return []
    since = (datetime.now(timezone.utc) - timedelta(hours=24)).replace(microsecond=0).isoformat()
    day = rtk_stats(root, since)
    parts = [rtk_line("24 h", day)] if day and day[0] else []
    parts.append(rtk_line("total", total))
    joined = "   ".join(parts)
    lines = [header("RTK", width)]
    lines += [joined] if len(ANSI.sub("", joined)) <= width - 2 else parts
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


def label_usage(segment):
    """Prefix an llmtrim segment with what it measures, coloured by its own value."""
    text = safe(segment)
    if "▓" in text or "░" in text:
        return f"{C['dim']}contexte{C['r']} {color_usage(text)}"
    names = {"✂": "économies", "◔": "quota utilisé", "♻": "cache"}
    mark = text[:1]
    if mark in names:
        body = text[1:].strip().replace(" cached", "")
        return f"{C['dim']}{names[mark]}{C['r']} {color_usage(mark + ' ' + body)}"
    return color_usage(text)


def section_usage(width, footer, tokens):
    usage = footer.get("usage", []) if VIEW["usage"] else []
    if not usage:
        return []
    age = int(time.time() - footer["ts"]) if footer.get("ts") else 0
    lines = [header("Conso", width, f"{age}s" if age > 30 else "")]
    labelled = [label_usage(u) for u in usage]
    joined = "   ".join(labelled)
    if len(ANSI.sub("", joined)) <= width - 2:
        lines.append(joined)
    else:
        lines += labelled
    if footer.get("cost") is not None and monitor.is_billed(tokens):
        lines.append(f"{C['warn']}hors quota{C['r']}  ${footer['cost']:.2f}")
    return lines + [""]


def section_subagents(cut, width, session):
    """Subagents still running; finished ones are not shown."""
    running = [(kind, desc) for live, kind, desc in (subagents_for(session) if VIEW["subs"] else []) if live]
    if not running:
        return []
    lines = [header("Subagents", width, f"{len(running)} actifs")]
    for sub_kind, desc in running[:SUBAGENT_MAX]:
        lines.append(f"{C['ok']}{SYM['working']} {cut(sub_kind + ' · ' + desc, width - 4)}{C['r']}")
    if len(running) > SUBAGENT_MAX:
        lines.append(f"{C['dim']}+{len(running) - SUBAGENT_MAX} autres{C['r']}")
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
    footer = read_footer(session)
    cwd = conversation_dir(agent, footer)
    title = cut(agent.get("terminal_title_stripped") or kind, width - 14)
    lines = [f"{state_color(status)}{ICON.get(status, status)}{C['r']}  {C['b']}{title}{C['r']}",
             f"{account_color(account)}● {safe(account or kind)}{C['r']}  {C['mod']}{safe(model or '?')}{C['r']}"
             f"  {C['dim']}{safe(agent.get('name') or agent['pane_id'])}{C['r']}"]
    plan = plan_line(tokens)
    if plan:
        lines.append(plan)
    lines.append("")
    lines += section_project(cut, width, cwd, tokens.get("pr", ""))
    lines += section_worktrees(cut, width, cwd)
    lines += section_services(cut, width, cwd)
    lines += section_usage(width, footer, tokens)
    lines += section_rtk(width, cwd)
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


SOURCES = [os.path.abspath(__file__), os.path.abspath(monitor.__file__)]


def sources_mtime():
    try:
        return max(os.path.getmtime(path) for path in SOURCES)
    except OSError:
        return 0


def main():
    load_ui()
    started = sources_mtime()
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
            if sources_mtime() > started:
                # code updated (git pull, cockpit setup): restart in place to pick it up
                if saved:
                    termios.tcsetattr(sys.stdin, termios.TCSADRAIN, saved)
                os.execv(sys.executable, [sys.executable, os.path.abspath(__file__)])
            if key == "q":
                break
            if key == "a":
                UI["mode"] = "conv" if UI["mode"] == "agents" else "agents"
            elif key == "P" and UI["mode"] == "conv":
                agent = target_agent()
                if agent:
                    prune_worktrees(conversation_dir(agent, read_footer(monitor.session_for(agent))))
            elif key == "e":
                UI["mode"] = "conv" if UI["mode"] == "space" else "space"
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
