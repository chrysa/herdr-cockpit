#!/usr/bin/env python3
"""Publish `$account` and `$model` on every agent row of herdr's sidebar.

Nothing in herdr or the plugin marketplace reports which Claude account (config
dir) and which model a pane runs, reliably for every session; everything else
this plugin used to do is now native or covered by a plugin.

Claude Code: the pane's agent session id locates the transcript under
<config_dir>/projects/*/<id>.jsonl; the config dir names the account
(~/.claude-perso -> "perso") and the last assistant entry carries the model.
Codex: the newest rollout file matching the session. opencode: the configured
"provider/model" (provider plays the account role).

Also publishes the conversation title under a per-account token (so the sidebar
colors it by account), and per space a subject and its name (busy/idle x
ecosystem). Tab names are herdr.auto-title's; this only puts "‼" in front of
the ones whose agent waits on you.

Commands: ensure (start in the background if needed), daemon, stop,
tabs (one pass of the "‼" mark on tabs waiting on you).
"""

import fcntl
import glob
import json
import os
import re
import shutil
import signal
import socket
import subprocess
import sys
import time
import urllib.parse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import events  # noqa: E402
import services  # noqa: E402
import subagents  # noqa: E402

PLUGIN_ID = "chrysa.agent-info"
SOURCE = f"plugin:{PLUGIN_ID}"
POLL_S = 8
TTL_MS = POLL_S * 20 * 1000
REFRESH_S = TTL_MS / 1000 / 3  # republish unchanged tokens before herdr expires them
TAIL_BYTES = 256 * 1024
SUB_ROWS = 3
SUB_TOKENS = (*(f"sub{i}" for i in range(1, SUB_ROWS + 1)), "sub_more")
TOKENS = ("account", "model", "topic_perso", "topic_pro", "topic_codex", "topic_other", "age", "doing", *SUB_TOKENS)
CONTROL = re.compile(r"[\x00-\x1f\x7f-\x9f]")
HOME = os.path.expanduser("~")
STATE_DIR = os.path.expanduser(f"~/.local/state/{PLUGIN_ID}")
LOCK = os.path.join(STATE_DIR, "daemon.lock")
PID = os.path.join(STATE_DIR, "daemon.pid")


def herdr_bin():
    """Absolute herdr path; plugin commands do not inherit the login PATH."""
    explicit = os.environ.get("HERDR_BIN_PATH", "")
    if explicit and os.path.isfile(explicit):
        return explicit
    for candidate in ("~/.local/bin/herdr", "/usr/local/bin/herdr", "/usr/bin/herdr"):
        path = os.path.expanduser(candidate)
        if os.path.isfile(path):
            return path
    return "herdr"


HERDR = herdr_bin()


def herdr(*args):
    proc = subprocess.run([HERDR, *args], capture_output=True, text=True, timeout=10)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or f"herdr {' '.join(args)} failed")
    return json.loads(proc.stdout) if proc.stdout.strip() else {}


def claude_dirs():
    """Distinct Claude config dirs (~/.claude is often a symlink to one of them)."""
    return sorted({os.path.realpath(d) for d in glob.glob(f"{HOME}/.claude*") if os.path.isdir(d)})


def short_model(model):
    """claude-opus-5-5 -> opus-5.5; other names unchanged (date suffix dropped)."""
    model = re.sub(r"-\d{8}$", "", model)
    m = re.match(r"claude-([a-z]+)-(\d+)-(\d+)", model)
    return f"{m.group(1)}-{m.group(2)}.{m.group(3)}" if m else model.removeprefix("claude-")


def last_match(path, pattern):
    """Last regex group 1 in the tail of a (possibly huge) jsonl file."""
    try:
        with open(path, "rb") as fh:
            fh.seek(0, os.SEEK_END)
            fh.seek(max(0, fh.tell() - TAIL_BYTES))
            hits = re.findall(pattern, fh.read().decode("utf-8", "replace"))
    except OSError:
        return None
    return hits[-1] if hits else None


TRANSCRIPTS = {}  # session id -> transcript path: the daemon ticks often, globbing is not free


def claude_transcript(session_id):
    known = TRANSCRIPTS.get(session_id)
    if known and os.path.exists(known):
        return known
    paths = [p for d in claude_dirs() for p in glob.glob(f"{d}/projects/*/{session_id}.jsonl")]
    if paths:
        TRANSCRIPTS[session_id] = paths[0]
    return paths[0] if paths else None


def claude_info(session_id):
    path = claude_transcript(session_id)
    if not path:
        return None, None
    config_dir = os.path.realpath(path).split("/projects/")[0]
    account = os.path.basename(config_dir).removeprefix(".claude").lstrip("-.") or "default"
    model = last_match(path, r'"model":\s*"(claude-[^"]+|[a-z][^"]*)"')
    return (short_model(model) if model and model != "<synthetic>" else None), account


# Agents column, line 2 (working Claude agents only): the session's last tool call,
# from the transcript tail ("Edit monitor.py", "Bash Run the tests").
DOING_MAX = 38
FILE_TOOLS = {"Read", "Edit", "Write", "MultiEdit", "NotebookEdit"}


def describe_tool(name, args):
    if name in FILE_TOOLS:
        detail = os.path.basename(str(args.get("file_path") or args.get("notebook_path") or ""))
    elif name == "Bash":
        detail = args.get("description") or args.get("command") or ""
    elif name in ("Grep", "Glob"):
        detail = args.get("pattern") or ""
    elif name in ("Agent", "Task"):
        detail = args.get("description") or ""
    elif name == "WebSearch":
        detail = args.get("query") or ""
    elif name == "WebFetch":
        detail = urllib.parse.urlsplit(str(args.get("url") or "")).netloc
    else:
        detail = ""
    if name.startswith("mcp__"):
        name = name.split("__")[-1]
    text = " ".join(CONTROL.sub(" ", f"{name} {detail}").split())
    return text if len(text) <= DOING_MAX else text[: DOING_MAX - 1] + "…"


def last_tool(path):
    """The last main-thread tool call in a Claude transcript tail, described, or None."""
    try:
        with open(path, "rb") as fh:
            fh.seek(0, os.SEEK_END)
            fh.seek(max(0, fh.tell() - TAIL_BYTES))
            lines = fh.read().decode("utf-8", "replace").splitlines()
    except OSError:
        return None
    for line in reversed(lines):
        if '"tool_use"' not in line:
            continue
        try:
            entry = json.loads(line)
        except ValueError:
            continue  # the tail's first line is usually cut
        content = (entry.get("message") or {}).get("content")
        if entry.get("type") != "assistant" or entry.get("isSidechain") or not isinstance(content, list):
            continue
        calls = [c for c in content if isinstance(c, dict) and c.get("type") == "tool_use"]
        if calls:
            return describe_tool(str(calls[-1].get("name") or ""), calls[-1].get("input") or {})
    return None


def agent_doing(agent):
    session = (agent.get("agent_session") or {}).get("value")
    if agent.get("agent_status") != "working" or agent.get("agent") != "claude" or not session:
        return None
    path = claude_transcript(session)
    return last_tool(path) if path else None


# Agents column, lines 3+: the Claude agent's subagents active in the last 30 min,
# "⑂ ● description" (● running, ◌ stalled, ✗ failed, ⊘ killed, ✓ done), what needs
# a look first, at most SUB_ROWS then "⑂ +N". Main transcripts are read
# incrementally (state["logs"]), never whole.
def agent_subagents(agent, logs, now):
    """[{id, status, description, last}] for a Claude agent, [] for any other."""
    session = (agent.get("agent_session") or {}).get("value")
    path = claude_transcript(session) if agent.get("agent") == "claude" and session else None
    if not path:
        return []
    log = logs.setdefault(path, subagents.MainLog(path))
    log.refresh(now)
    return subagents.listing(path, log, now)


def sub_tokens(subs):
    lines = [f"⑂ {subagents.GLYPHS.get(s['status'], '•')} {s['description']}" for s in subs]
    extra = len(lines) - SUB_ROWS
    return {**{f"sub{i}": lines[i - 1] if i <= len(lines) else None for i in range(1, SUB_ROWS + 1)},
            "sub_more": f"⑂ +{extra}" if extra > 0 else None}


# Agents column: how long the agent has been in its state ("12m", "3h05", "2j").
# herdr reports no timestamps, so the daemon notes when each (status,
# state_change_seq) was first seen and keeps it in SINCE across restarts.
SINCE = os.path.join(STATE_DIR, "since.json")
# Right of the tab bar (cockpit's herdr-tabbar prints this file): account, model and
# usagebar's context of the focused agent. Written here, on events, so the tab bar
# command only reads a file; querying herdr from it timed out under load.
TABBAR = os.path.join(STATE_DIR, "tabbar")


def tabbar_line(agents, accounts):
    """account  model  context of the focused agent; "" when none is focused."""
    agent = next((a for a in agents if a.get("focused")), None)
    if not agent:
        return ""
    account, model = accounts.get(agent["pane_id"], (None, None))
    context = (agent.get("tokens") or {}).get("context")
    return "  ".join(CONTROL.sub("", str(p)) for p in (account, model, context) if p)


def write_tabbar(line, path=None):
    path = path or TABBAR
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w") as fh:
        fh.write(line + "\n" if line else "")
    os.replace(tmp, path)


def age_label(seconds):
    minutes = int(seconds // 60)
    if minutes < 1:
        return None
    if minutes < 60:
        return f"{minutes}m"
    hours = minutes // 60
    return f"{hours}h{minutes % 60:02d}" if hours < 24 else f"{hours // 24}j"


def track_since(since, agents, now):
    """since[pane] = [status, state_change_seq, first seen], reset when either changes."""
    for agent in agents:
        key = [agent.get("agent_status"), agent.get("state_change_seq")]
        entry = since.get(agent["pane_id"])
        if not entry or entry[:2] != key:
            since[agent["pane_id"]] = [*key, now]
    for gone in set(since) - {a["pane_id"] for a in agents}:
        del since[gone]


def load_since():
    try:
        with open(SINCE) as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_since(since):
    tmp = SINCE + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(since, fh)
    os.replace(tmp, SINCE)


# Desktop notification when an agent starts waiting on you: herdr's own toasts stay
# inside herdr. Once per blocked state, never for the focused pane nor for agents
# already blocked when the daemon starts. AGENT_INFO_NOTIFY=0 turns it off.
NOTIFY = os.environ.get("AGENT_INFO_NOTIFY", "1") != "0"


def desktop_notify(title, body):
    def clean(text):  # notify-send bodies take markup: agent text must not
        return CONTROL.sub("", text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    if shutil.which("notify-send"):
        # "--": a terminal title starting with "-" must not be read as an option
        cmd = ["notify-send", "--app-name=herdr", "--", clean(title), clean(body)]
    elif shutil.which("osascript"):
        cmd = ["osascript", "-e", "on run argv", "-e",
               "display notification (item 2 of argv) with title (item 1 of argv)", "-e", "end run",
               CONTROL.sub("", title), CONTROL.sub("", body)]
    else:
        return
    subprocess.run(cmd, capture_output=True, timeout=5, check=False)


def notify_blocked(agents, state, labels_by_ws, names=None):
    names = names or {}
    blocked = {f"{a['pane_id']}:{a.get('state_change_seq')}": a for a in agents if a.get("agent_status") == "blocked"}
    for key, agent in blocked.items():
        if key in state["notified"]:
            continue
        state["notified"].add(key)
        if NOTIFY and not state["first"] and not agent.get("focused"):
            space = labels_by_ws.get(agent.get("workspace_id")) or "herdr"
            desktop_notify(f"Agent en attente · {space}", names.get(agent["pane_id"]) or topic_title(agent))
    state["notified"].intersection_update(blocked)


def codex_info(session_id):
    files = glob.glob(f"{HOME}/.codex/sessions/**/*{session_id}*.jsonl", recursive=True)
    if not files:
        return None, None
    model = last_match(max(files, key=os.path.getmtime), r'"model":\s*"([^"]+)"')
    return (short_model(model) if model else None), "codex"


def opencode_info(cwd):
    candidates = [
        os.path.join(cwd or "", "opencode.json"),
        os.path.join(os.environ.get("XDG_CONFIG_HOME", f"{HOME}/.config"), "opencode", "opencode.json"),
    ]
    for path in candidates:
        try:
            with open(path) as fh:
                model = json.load(fh).get("model")
        except (OSError, ValueError):
            continue
        if model:
            provider, _, name = model.partition("/")
            return (name or provider), (provider if name else "opencode")
    return None, "opencode"


def agent_info(agent):
    """(model, account) for any supported agent."""
    kind = agent.get("agent", "")
    session = (agent.get("agent_session") or {}).get("value")
    if kind == "claude" and session:
        return claude_info(session)
    if kind == "codex" and session:
        return codex_info(session)
    if kind in ("opencode", "open_code"):
        return opencode_info(agent.get("cwd"))
    return None, None


def publish(pane_id, tokens):
    args = ["pane", "report-metadata", pane_id, "--source", SOURCE, "--ttl-ms", str(TTL_MS)]
    for name in TOKENS:
        value = CONTROL.sub("", tokens.get(name) or "")
        args += ["--token", f"{name}={value}"] if value else ["--clear-token", name]
    herdr(*args)


# A tab whose agent waits on you (herdr's tab agent_status "blocked") carries
# TAB_MARK in front of its name, and only that one. Tab names are otherwise
# herdr.auto-title's, which leaves a tab renamed by anyone else alone and names it
# again once its name is cleared (both documented). So the mark comes off a tab
# auto-title named by clearing the name (auto-title names it afresh), and off a tab
# the user named by putting the name back without it (it stays theirs). Which kind
# a tab is comes from auto-title's lock file, read when the mark goes on, and is
# kept in MARKED so a daemon restart takes the mark off the right way.
TAB_MARK = "‼ "
MARKED = os.path.join(STATE_DIR, "marked-tabs.json")  # tab_id -> "hand" | "auto"
AUTO_TITLE_DIR = os.path.join(os.environ.get("XDG_CONFIG_HOME", f"{HOME}/.config"), "herdr-auto-title")


def manual_file():
    """auto-title's lock file: HERDR_AUTO_TITLE_MANUAL_FILE in its config.env, else the default."""
    try:
        with open(os.path.join(AUTO_TITLE_DIR, "config.env")) as fh:
            for line in fh:
                key, _, value = line.strip().partition("=")
                if key == "HERDR_AUTO_TITLE_MANUAL_FILE" and value:
                    return value
    except OSError:
        pass
    return os.path.join(AUTO_TITLE_DIR, "manual-names.json")


def hand_named():
    """Tab ids auto-title leaves alone because someone renamed them."""
    try:
        with open(manual_file()) as fh:
            locked = json.load(fh).get("locked_tabs") or {}
        return set(locked) if isinstance(locked, dict) else set()
    except (OSError, ValueError, AttributeError):
        return set()


def load_marked():
    try:
        with open(MARKED) as fh:
            data = json.load(fh)
        return {k: v for k, v in data.items() if v in ("hand", "auto")} if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_marked(marked):
    os.makedirs(STATE_DIR, exist_ok=True)
    tmp = MARKED + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(marked, fh)
    os.replace(tmp, MARKED)


def mark_tabs(tabs, marked, hand=None):
    """Rename tabs so that exactly the blocked ones carry TAB_MARK; True if marked changed."""
    before = dict(marked)
    live = set()
    for tab in tabs:
        tab_id, label = tab.get("tab_id"), tab.get("label") or ""
        if not tab_id:
            continue
        live.add(tab_id)
        blocked = tab.get("agent_status") == "blocked"
        if blocked and label and not label.startswith(TAB_MARK):
            hand = hand_named() if hand is None else hand
            try:
                herdr("tab", "rename", tab_id, TAB_MARK + label)
                marked[tab_id] = "hand" if tab_id in hand else "auto"
            except RuntimeError:
                pass  # closed meanwhile
        elif not blocked and label.startswith(TAB_MARK):
            kind = marked.get(tab_id, "hand")  # unknown: keep the name rather than lose it
            try:
                herdr("tab", "rename", tab_id, label[len(TAB_MARK):] if kind == "hand" else "")
                marked.pop(tab_id, None)
            except RuntimeError:
                pass
    for gone in set(marked) - live:
        del marked[gone]
    return marked != before


# Agents column: the agent's name (agent_name), published under the token of its
# account (one is set, the others cleared) so the sidebar colors it by account with
# fixed per-token colors; herdr rules can only match a token's own value.
NAMED_ACCOUNTS = ("perso", "pro", "codex")
TOPIC_TOKENS = tuple(f"topic_{name}" for name in (*NAMED_ACCOUNTS, "other"))
GENERIC_TITLES = {"", "claude", "codex", "opencode"}
# herdr.auto-title names a tab "<context> › <activity>" from the conversation and
# cuts it to its max length; a name at least this long that starts the
# conversation title is taken as derived from it, not chosen by hand.
DERIVED_MIN = 12
# auto-title's context may hold the branch ("repo › main › activity"); a default
# branch says nothing and pushes the activity past the sidebar's edge.
DEFAULT_BRANCHES = {"main", "master", "develop"}


def drop_default_branch(label):
    """"repo › main › activity" -> "repo › activity"; first and last segments stay."""
    parts = label.split(" › ")
    return " › ".join(p for i, p in enumerate(parts)
                      if i in (0, len(parts) - 1) or p.strip() not in DEFAULT_BRANCHES)


def topic_title(agent):
    """The agent's subject: live terminal title, else the reported session title."""
    live = CONTROL.sub("", agent.get("terminal_title_stripped") or "").strip()
    reported = CONTROL.sub("", agent.get("title") or "").strip()
    return live if live.lower() not in GENERIC_TITLES else reported or live or agent.get("agent") or ""


def agent_name(agent, tab_label, shared=False):
    """The agent's name in the sidebar: its tab's name, as in the tab bar.

    The conversation title instead when the tab is unnamed or generic, or when its
    name was derived from that title (auto-title cuts it; the title is complete).
    A tab holding several agents adds each one's title so their rows differ.
    """
    title = topic_title(agent)
    label = drop_default_branch(CONTROL.sub("", tab_label or "").removeprefix(TAB_MARK).strip())
    activity = label.rsplit(" › ", 1)[-1].strip()
    derived = activity == title or (len(activity) >= DERIVED_MIN and title.startswith(activity))
    if label.lower() in GENERIC_TITLES or label in DEFAULT_BRANCHES or label.isdigit() or derived:
        return title
    return f"{label} · {title}" if shared and title and title != label else label


def agent_names(agents, tabs):
    """pane_id -> sidebar name, from `herdr tab list` tabs."""
    labels = {t.get("tab_id"): t.get("label") or "" for t in tabs}
    per_tab = {}
    for agent in agents:
        per_tab[agent.get("tab_id")] = per_tab.get(agent.get("tab_id"), 0) + 1
    return {a["pane_id"]: agent_name(a, labels.get(a.get("tab_id"), ""), per_tab[a.get("tab_id")] > 1)
            for a in agents}


def topic_tokens(agent, account, name=None):
    """{topic_<account>: name, other topic tokens: None} for one agent row."""
    title = name or topic_title(agent)
    key = f"topic_{account}" if account in NAMED_ACCOUNTS else "topic_other"
    return {token: (title or None) if token == key else None for token in TOPIC_TOKENS}


# Spaces column, lines 2+: only the agents waiting on you (blocked), longest wait
# first, one line each ("‼ subject"), at most WAIT_ROWS, then "+N en attente".
# Every other agent is in the Agents column, so no space line reads like an agent.
# Line 1: the space name under one of six tokens, busy (holds agents, bold) or idle
# (dim) x ecosystem color, one set and the others cleared: herdr row styles are
# static and rules only match a token's own value, so the state and the ecosystem
# must be in the token name. A space is the child of the space whose folder holds
# its own (plateform_socle in Forge-Stack-Workshop/), else of the space whose name
# plus "-" starts its own (padam-av-GHA next to padam-av): it shows "↳ name" (the
# parent's prefix dropped), takes its parent's ecosystem, and is moved right after
# its parent. Nothing is listed by hand: folders come from the panes' cwd.
ECOSYSTEMS = (("pro", lambda name: name.startswith("padam")), ("perso", lambda name: name == "chrysa"))
NAME_TOKENS = tuple(f"space_{state}_{eco}" for state in ("busy", "idle") for eco in ("pro", "perso", "other"))
WAIT_ROWS = 3
WAIT_TOKENS = (*(f"wait{i}" for i in range(1, WAIT_ROWS + 1)), "wait_more")
# Same line: agents and subagents counted per state, one group per account in its
# color ("‼1 ◐2 ○1 ⑂●2✓1"): count_<perso|pro|codex|other>. A space where every
# agent sits idle shows no count: its dimmed name already says so.
COUNT_TOKENS = tuple(f"count_{name}" for name in (*NAMED_ACCOUNTS, "other"))
AGENT_GLYPHS = {"blocked": "‼", "working": "◐", "done": "✓", "idle": "○"}
ACTIVE_STATES = ("working", "blocked", "done")  # bold space name, counts shown
AGENT_TOKENS = (*WAIT_TOKENS, *COUNT_TOKENS)
SPACE_TOKENS = (*AGENT_TOKENS, *NAME_TOKENS)


def counts_label(statuses, sub_statuses):
    """"‼1 ◐2 ⑂●2✓1": agents then subagents per state, zeros left out; None if empty."""
    parts = [f"{glyph}{statuses.count(state)}" for state, glyph in AGENT_GLYPHS.items() if state in statuses]
    subs = "".join(f"{glyph}{sub_statuses.count(state)}" for state, glyph in subagents.GLYPHS.items()
                   if state in sub_statuses)
    return " ".join(parts + ([f"⑂{subs}"] if subs else [])) or None


def ecosystem(label):
    return next((eco for eco, matches in ECOSYSTEMS if matches(label)), "other")


def space_folders(workspaces, panes):
    """workspace_id -> its folder: a pane's cwd named like the space, else the most common one."""
    cwds = {}
    for pane in panes:
        if pane.get("cwd"):
            cwds.setdefault(pane.get("workspace_id"), []).append(os.path.normpath(pane["cwd"]))
    folders = {}
    for workspace in workspaces:
        paths = cwds.get(workspace.get("workspace_id"), [])
        label = CONTROL.sub("", workspace.get("label") or "")
        pool = [path for path in paths if os.path.basename(path) == label] or paths
        folders[workspace.get("workspace_id")] = max(pool, key=lambda p: (pool.count(p), -len(p))) if pool else None
    return folders


def inside(folder, parent):
    return bool(folder and parent) and folder != parent and folder.startswith(parent.rstrip("/") + "/")


def space_parents(spaces):
    """[(workspace_id, label, folder)] -> {workspace_id: parent workspace_id}.

    The closest space whose folder holds this one's, else the longest label that plus
    "-" starts this one's; a name link that would close a loop is skipped.
    """
    parents = {}
    for ws, _, folder in spaces:
        holders = [(len(other_folder), other) for other, _, other_folder in spaces
                   if other != ws and inside(folder, other_folder)]
        if holders:
            parents[ws] = max(holders)[1]

    def above(ws, target):  # is target ws or one of its parents?
        seen = set()
        while ws is not None and ws not in seen:
            if ws == target:
                return True
            seen.add(ws)
            ws = parents.get(ws)
        return False

    for ws, label, _ in spaces:
        if ws in parents or not label:
            continue
        prefixes = sorted(((len(other_label), other) for other, other_label, _ in spaces
                           if other != ws and other_label and label.startswith(other_label + "-")), reverse=True)
        parent = next((other for _, other in prefixes if not above(other, ws)), None)
        if parent is not None:
            parents[ws] = parent
    return parents


def grouped_order(ids, parents):
    """Sidebar order with every space right after its parent; the others keep their place."""
    children = {}
    for ws in ids:
        if ws in parents:
            children.setdefault(parents[ws], []).append(ws)
    order = []

    def add(ws):
        order.append(ws)
        for child in children.get(ws, []):
            add(child)

    for ws in ids:
        if ws not in parents:
            add(ws)
    return order


def moves_to(current, wanted):
    """(workspace_id, insert_index) moves turning current into wanted (index = final place)."""
    order, moves = list(current), []
    for index, ws in enumerate(wanted):
        if order[index] != ws:
            order.remove(ws)
            order.insert(index, ws)
            moves.append((ws, index))
    return moves


def short_name(label, parent_label):
    """label, or "↳ label" under a parent, its "parent-" prefix dropped."""
    if parent_label is None:
        return label
    return f"↳ {label.removeprefix(parent_label + '-') if label != parent_label else label}"


WORDS = re.compile(r"[^-_. ]+[-_. ]*")  # "plateform_socle" -> "plateform_", "socle"


def shown_names(spaces, parents):
    """workspace_id -> sidebar name: short_name(), then children of one parent that
    start with the same word drop the leading words they all share
    (plateform_socle and plateform_service_catalog show "↳ socle" and
    "↳ service_catalog"); every name keeps at least one word."""
    label_of = {ws: label for ws, label, _ in spaces}
    names = {ws: short_name(label, label_of.get(parents.get(ws))) for ws, label, _ in spaces}
    groups = {}
    for ws in label_of:
        words = WORDS.findall(names[ws][2:]) if ws in parents else []
        if words:
            groups.setdefault((parents[ws], words[0]), []).append((ws, words))
    for members in groups.values():
        if len(members) < 2:
            continue
        shared = 0
        while (all(len(words) > shared + 1 for _, words in members)
               and len({tuple(words[:shared + 1]) for _, words in members}) == 1):
            shared += 1
        for ws, words in members:
            names[ws] = f"↳ {''.join(words[shared:])}"
    return names


def name_tokens(shown, eco, busy):
    """{space_<busy|idle>_<eco>: shown name, the other name tokens: None}."""
    key = f"space_{'busy' if busy else 'idle'}_{eco}"
    return {name: (shown or None) if name == key else None for name in NAME_TOKENS}


def request(method, params):
    """One socket request; herdr's CLI has no command for some methods (workspace.move)."""
    with socket.socket(socket.AF_UNIX) as sock:
        sock.settimeout(5)
        sock.connect(events.socket_path())
        sock.sendall((json.dumps({"id": PLUGIN_ID, "method": method, "params": params}) + "\n").encode())
        buf = b""
        while not buf.endswith(b"\n"):
            chunk = sock.recv(65536)
            if not chunk:
                break
            buf += chunk
    reply = json.loads(buf or b"{}")
    if "error" in reply:
        raise RuntimeError(f"{method}: {reply['error']}")
    return reply


def group_spaces(ids, parents, state):
    """Move children after their parent; a wanted order herdr did not take is not retried."""
    wanted = grouped_order(ids, parents)
    if wanted == ids:
        state["tried_order"] = None
        return
    if state.get("tried_order") == wanted:
        return
    state["tried_order"] = wanted
    for ws, index in moves_to(ids, wanted):
        request("workspace.move", {"workspace_id": ws, "insert_index": index})


def space_tokens(agents, details=None):
    """workspace_id -> count and waiting-agent tokens, for every space that holds agents.

    details: pane_id -> {"account": ..., "subs": [subagent statuses], "name": sidebar name}
    (missing: other account, no subagents, conversation title).
    """
    details = details or {}
    by_space = {}
    for agent in agents:
        by_space.setdefault(agent.get("workspace_id"), []).append(agent)
    tokens = {}
    for ws, members in by_space.items():
        waiting = sorted((a for a in members if a.get("agent_status") == "blocked"),
                         key=lambda a: a.get("state_change_seq") or 0)
        lines = [f"‼ {details.get(a.get('pane_id'), {}).get('name') or topic_title(a) or 'agent'}" for a in waiting]
        extra = len(lines) - WAIT_ROWS
        groups = {}
        active = any(a.get("agent_status") in ACTIVE_STATES for a in members)
        for agent in members if active else ():
            info = details.get(agent.get("pane_id"), {})
            account = info.get("account") if info.get("account") in NAMED_ACCOUNTS else "other"
            statuses, subs = groups.setdefault(account, ([], []))
            statuses.append(agent.get("agent_status"))
            subs.extend(info.get("subs", []))
        tokens[ws] = {**{f"wait{i}": lines[i - 1] if i <= len(lines) else None for i in range(1, WAIT_ROWS + 1)},
                      "wait_more": f"+{extra} en attente" if extra > 0 else None,
                      **{f"count_{name}": counts_label(*groups[name]) if name in groups else None
                         for name in (*NAMED_ACCOUNTS, "other")}}
    return tokens


def publish_space(workspace_id, tokens):
    args = ["workspace", "report-metadata", workspace_id, "--source", SOURCE, "--ttl-ms", str(TTL_MS)]
    for name in SPACE_TOKENS:
        value = CONTROL.sub("", tokens.get(name) or "")
        args += ["--token", f"{name}={value}"] if value else ["--clear-token", name]
    herdr(*args)


def new_state():
    """Daemon memory across ticks: state ages and the blocked states already notified."""
    return {"since": {}, "notified": set(), "first": True, "logs": {}, "watch": [], "panes": [], "marked": {},
            "accounts": {}}


def tick(shown, state=None, now=None):
    state = new_state() if state is None else state
    now = time.time() if now is None else now
    if time.monotonic() - shown.get("_refreshed", 0) > REFRESH_S:
        shown.clear()
        shown["_refreshed"] = time.monotonic()
    agents = herdr("agent", "list").get("result", {}).get("agents", [])
    track_since(state["since"], agents, now)
    tabs = herdr("tab", "list").get("result", {}).get("tabs", [])
    if mark_tabs(tabs, state["marked"]):
        save_marked(state["marked"])
    names = agent_names(agents, tabs)
    details = {}
    for agent in agents:
        model, account = agent_info(agent)
        state["accounts"][agent["pane_id"]] = (account, model)
        subs = agent_subagents(agent, state["logs"], now)
        name = names[agent["pane_id"]]
        details[agent["pane_id"]] = {"account": account, "subs": [s["status"] for s in subs], "name": name}
        tokens = {"account": account, "model": model, **topic_tokens(agent, account, name),
                  "age": age_label(now - state["since"][agent["pane_id"]][2]), "doing": agent_doing(agent),
                  **sub_tokens(subs)}
        if shown.get(agent["pane_id"]) != tokens:
            publish(agent["pane_id"], tokens)
            shown[agent["pane_id"]] = tokens
    state["logs"] = {path: log for path, log in state["logs"].items() if os.path.exists(path)}
    # What wakes the daemon besides herdr events: each Claude transcript and its
    # subagents folder (a new subagent adds a file there).
    state["watch"] = [p for path in state["logs"] for p in (path, os.path.join(path.removesuffix(".jsonl"), "subagents"))]
    state["panes"] = [a["pane_id"] for a in agents]
    line = tabbar_line(agents, state["accounts"])
    if line != state.get("tabbar"):
        write_tabbar(line)
        state["tabbar"] = line
    subjects = space_tokens(agents, details)
    # Bold space name: an agent there works, waits on you or has finished. A space
    # whose agents all sit idle (herdr relaunches one in each space on restore) dims.
    active = {a.get("workspace_id") for a in agents if a.get("agent_status") in ACTIVE_STATES}
    workspaces = herdr("workspace", "list").get("result", {}).get("workspaces", [])
    labels = [CONTROL.sub("", w.get("label") or "") for w in workspaces]
    notify_blocked(agents, state, {w.get("workspace_id"): label for w, label in zip(workspaces, labels)}, names)
    state["first"] = False
    folders = space_folders(workspaces, herdr("pane", "list").get("result", {}).get("panes", []))
    listed = [(w["workspace_id"], label, folders.get(w["workspace_id"]))
              for w, label in zip(workspaces, labels) if w.get("workspace_id")]
    parents = space_parents(listed)
    label_of = {ws: label for ws, label, _ in listed}
    display = shown_names(listed, parents)

    def root(ws):
        while ws in parents:
            ws = parents[ws]
        return ws

    spaces = {
        f"ws:{ws}": {**dict.fromkeys(AGENT_TOKENS), **subjects.get(ws, {}),
                     **name_tokens(display[ws], ecosystem(label_of[root(ws)]), ws in active)}
        for ws, label, _ in listed
    }
    for key, tokens in spaces.items():
        if shown.get(key) != tokens:
            publish_space(key[3:], tokens)
            shown[key] = tokens
    live = {a["pane_id"] for a in agents} | set(spaces)
    for gone in set(shown) - live - {"_refreshed"}:
        shown.pop(gone, None)
        if gone.startswith("ws:"):
            try:
                publish_space(gone[3:], {})  # space no longer listed: clear its tokens
            except RuntimeError:
                pass  # space closed meanwhile
    group_spaces([ws for ws, _, _ in listed], parents, state)


def daemon():
    os.makedirs(STATE_DIR, exist_ok=True)
    lock = open(LOCK, "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return
    with open(PID, "w") as fh:
        fh.write(str(os.getpid()))
    shown, failures = {}, 0
    state = {**new_state(), "since": load_since(), "marked": load_marked()}
    saved = json.dumps(state["since"])
    stream, snapshots_at = events.EventStream(), 0.0
    while failures < 10:
        try:
            if time.monotonic() - snapshots_at >= POLL_S:  # docker ps / ss: slow, not urgent
                services.save_snapshots()
                snapshots_at = time.monotonic()
            tick(shown, state)
            if json.dumps(state["since"]) != saved:
                save_since(state["since"])
                saved = json.dumps(state["since"])
            stream.follow(state["panes"])
            failures = 0
        except Exception:
            failures += 1
        wait_for_change(stream, state["watch"], POLL_S)


def wait_for_change(stream, watch, longest):
    """Until a herdr event, a watched file changes, or longest seconds (ages, stalls)."""
    deadline = time.monotonic() + longest
    before = events.file_signature(watch)
    while time.monotonic() < deadline:
        if stream.wait(min(events.FILE_CHECK_S, max(0.0, deadline - time.monotonic()))):
            return
        if events.file_signature(watch) != before:
            return


def mark_tabs_once():
    """One mark pass outside the daemon (`monitor.py tabs`)."""
    marked = load_marked()
    if mark_tabs(herdr("tab", "list").get("result", {}).get("tabs", []), marked):
        save_marked(marked)


def running_pid():
    try:
        pid = int(open(PID).read().strip())
        os.kill(pid, 0)
        return pid
    except (OSError, ValueError):
        return None


def ensure():
    if running_pid():
        return
    os.makedirs(STATE_DIR, exist_ok=True)
    subprocess.Popen(
        [sys.executable, os.path.abspath(__file__), "daemon"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )


def stop():
    pid = running_pid()
    if pid:
        os.kill(pid, signal.SIGTERM)


def main():
    {"ensure": ensure, "daemon": daemon, "stop": stop, "tabs": mark_tabs_once}.get(
        sys.argv[1] if len(sys.argv) > 1 else "ensure", ensure
    )()


if __name__ == "__main__":
    main()
