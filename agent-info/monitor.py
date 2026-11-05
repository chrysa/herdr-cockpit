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
ecosystem). Tab names are left to herdr.auto-title.

Commands: ensure (start in the background if needed), daemon, stop,
tabs (clear tab names an older version prefixed with ◐ ‼ ✓).
"""

import fcntl
import glob
import json
import os
import re
import signal
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import services  # noqa: E402

PLUGIN_ID = "chrysa.agent-info"
SOURCE = f"plugin:{PLUGIN_ID}"
POLL_S = 8
TTL_MS = POLL_S * 20 * 1000
REFRESH_S = TTL_MS / 1000 / 3  # republish unchanged tokens before herdr expires them
TAIL_BYTES = 256 * 1024
TOKENS = ("account", "model", "topic_perso", "topic_pro", "topic_codex", "topic_other")
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


def claude_info(session_id):
    for path in [p for d in claude_dirs() for p in glob.glob(f"{d}/projects/*/{session_id}.jsonl")]:
        config_dir = os.path.realpath(path).split("/projects/")[0]
        account = os.path.basename(config_dir).removeprefix(".claude").lstrip("-.") or "default"
        model = last_match(path, r'"model":\s*"(claude-[^"]+|[a-z][^"]*)"')
        return (short_model(model) if model and model != "<synthetic>" else None), account
    return None, None


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


# Tab names belong to herdr.auto-title alone. This plugin used to put the
# conversation state (◐ ‼ ✓) in front of them, but auto-title reads any rename it
# did not make as the user's and stops naming that tab for good. The state stays
# in the sidebar (Agents column, Spaces state icon).
OLD_TAB_PREFIX = re.compile("^(?:[◐‼✓] )+")


def release_tabs():
    """Clear tab names this plugin prefixed, once: auto-title names cleared tabs again."""
    for tab in herdr("tab", "list").get("result", {}).get("tabs", []):
        if OLD_TAB_PREFIX.match(tab.get("label") or ""):
            herdr("tab", "rename", tab["tab_id"], "")


# Agents column: the conversation title, published under the token of its account
# (one is set, the others cleared) so the sidebar colors the title by account with
# fixed per-token colors; herdr rules can only match a token's own value.
NAMED_ACCOUNTS = ("perso", "pro", "codex")
TOPIC_TOKENS = tuple(f"topic_{name}" for name in (*NAMED_ACCOUNTS, "other"))
GENERIC_TITLES = {"", "claude", "codex", "opencode"}


def topic_title(agent):
    """The agent's subject: live terminal title, else the reported session title."""
    live = CONTROL.sub("", agent.get("terminal_title_stripped") or "").strip()
    reported = CONTROL.sub("", agent.get("title") or "").strip()
    return live if live.lower() not in GENERIC_TITLES else reported or live or agent.get("agent") or ""


def topic_tokens(agent, account):
    """{topic_<account>: title, other topic tokens: None} for one agent row."""
    title = topic_title(agent)
    key = f"topic_{account}" if account in NAMED_ACCOUNTS else "topic_other"
    return {name: (title or None) if name == key else None for name in TOPIC_TOKENS}


# Spaces column, line 2: one subject per space (a blocked agent's first, else the
# agent that changed state last) and "+N" for its other distinct subjects.
# Line 1: the space name under one of six tokens, busy (holds agents, bold) or idle
# (dim) x ecosystem color, one set and the others cleared: herdr row styles are
# static and rules only match a token's own value, so the state and the ecosystem
# must be in the token name. A space named after another one plus "-suffix" (e.g.
# padam-av-GHA next to padam-av) shows "↳ suffix" so long names are not cut.
ECOSYSTEMS = (("pro", lambda name: name.startswith("padam")), ("perso", lambda name: name == "chrysa"))
NAME_TOKENS = tuple(f"space_{state}_{eco}" for state in ("busy", "idle") for eco in ("pro", "perso", "other"))
SPACE_TOKENS = ("theme", "more", *NAME_TOKENS)


def ecosystem(label):
    return next((eco for eco, matches in ECOSYSTEMS if matches(label)), "other")


def short_name(label, labels):
    """label, or "↳ suffix" when another space's label plus "-" prefixes it (longest wins)."""
    parents = [p for p in labels if p and p != label and label.startswith(p + "-")]
    return f"↳ {label[len(max(parents, key=len)) + 1:]}" if parents else label


def name_tokens(label, labels, busy):
    """{space_<busy|idle>_<ecosystem>: shown name, the other name tokens: None}."""
    key = f"space_{'busy' if busy else 'idle'}_{ecosystem(label)}"
    shown = short_name(label, labels) if label else None
    return {name: shown if name == key else None for name in NAME_TOKENS}


def space_tokens(agents):
    """workspace_id -> Spaces-column tokens, from the agent list."""
    by_space = {}
    for agent in agents:
        by_space.setdefault(agent.get("workspace_id"), []).append(agent)
    tokens = {}
    for ws, members in by_space.items():
        ranked = sorted(members, key=lambda a: (a.get("agent_status") == "blocked", a.get("state_change_seq") or 0),
                        reverse=True)
        subjects = list(dict.fromkeys(topic_title(a) for a in ranked))
        real = [s for s in subjects if s.lower() not in GENERIC_TITLES] or subjects
        others = len(real) - 1
        tokens[ws] = {"theme": real[0] or None, "more": f"+{others}" if others > 0 else None}
    return tokens


def publish_space(workspace_id, tokens):
    args = ["workspace", "report-metadata", workspace_id, "--source", SOURCE, "--ttl-ms", str(TTL_MS)]
    for name in SPACE_TOKENS:
        value = CONTROL.sub("", tokens.get(name) or "")
        args += ["--token", f"{name}={value}"] if value else ["--clear-token", name]
    herdr(*args)


def tick(shown):
    if time.monotonic() - shown.get("_refreshed", 0) > REFRESH_S:
        shown.clear()
        shown["_refreshed"] = time.monotonic()
    agents = herdr("agent", "list").get("result", {}).get("agents", [])
    for agent in agents:
        model, account = agent_info(agent)
        tokens = {"account": account, "model": model, **topic_tokens(agent, account)}
        if shown.get(agent["pane_id"]) != tokens:
            publish(agent["pane_id"], tokens)
            shown[agent["pane_id"]] = tokens
    subjects = space_tokens(agents)
    workspaces = herdr("workspace", "list").get("result", {}).get("workspaces", [])
    labels = [CONTROL.sub("", w.get("label") or "") for w in workspaces]
    spaces = {
        f"ws:{w['workspace_id']}": {"theme": None, "more": None, **subjects.get(w["workspace_id"], {}),
                                    **name_tokens(label, labels, w["workspace_id"] in subjects)}
        for w, label in zip(workspaces, labels) if w.get("workspace_id")
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
    try:
        release_tabs()
    except (RuntimeError, OSError, ValueError, subprocess.TimeoutExpired):
        pass  # names left prefixed stay as they are; nothing else depends on it
    while failures < 10:
        try:
            services.save_snapshots()
            tick(shown)
            failures = 0
        except Exception:
            failures += 1
        time.sleep(POLL_S)


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
    {"ensure": ensure, "daemon": daemon, "stop": stop, "tabs": release_tabs}.get(
        sys.argv[1] if len(sys.argv) > 1 else "ensure", ensure
    )()


if __name__ == "__main__":
    main()
