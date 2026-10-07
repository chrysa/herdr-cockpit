#!/usr/bin/env python3
"""herdr-cockpit/agent-info - per-agent `model` and `account` sidebar tokens.

Claude Code: the pane's agent session id locates the transcript under
<config_dir>/projects/*/<id>.jsonl; the last assistant entry carries the model,
and the config dir it lives in names the account (~/.claude-perso -> "perso").
Codex: the newest rollout file under ~/.codex/sessions matching the session id
carries the model in its turn context.

Commands:
  ensure  start the background monitor if not already running
  daemon  run the monitor loop in the foreground
  stop    stop the monitor and clear every token it published
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

PLUGIN_ID = "chrysa.agent-info"
SOURCE = f"plugin:{PLUGIN_ID}"
POLL_S = 8
TTL_MS = POLL_S * 20 * 1000
TAIL_BYTES = 256 * 1024
TOKENS = ("model", "account", "doing", "todo", "git", "subs")
DOING_MAX = 34
STATE_DIR = os.path.expanduser(f"~/.local/state/{PLUGIN_ID}")
LOCK = os.path.join(STATE_DIR, "daemon.lock")
PID = os.path.join(STATE_DIR, "daemon.pid")
HOME = os.path.expanduser("~")


def claude_dirs():
    """Distinct Claude config dirs (~/.claude is often a symlink to one of them)."""
    return sorted({os.path.realpath(d) for d in glob.glob(f"{HOME}/.claude*") if os.path.isdir(d)})


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


def short_model(model):
    """claude-opus-5-5 -> opus-5.5, gpt-5.4-mini stays as is."""
    model = re.sub(r"-\d{8}$", "", model)
    m = re.match(r"claude-([a-z]+)-(\d+)-(\d+)", model)
    if m:
        return f"{m.group(1)}-{m.group(2)}.{m.group(3)}"
    return model.removeprefix("claude-")


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
    """(model, account) for a Claude Code session id."""
    for path in [p for d in claude_dirs() for p in glob.glob(f"{d}/projects/*/{session_id}.jsonl")]:
        config_dir = os.path.realpath(path).split("/projects/")[0]
        account = os.path.basename(config_dir).removeprefix(".claude").lstrip("-.") or "default"
        model = last_match(path, r'"model":"(claude-[^"]+|[a-z][^"]*)"')
        if model == "<synthetic>":
            model = None
        return (short_model(model) if model else None), account
    return None, None


def claude_tasks(session_id):
    """(doing, todo) from Claude Code's per-session task list, or (None, None).

    doing: the in-progress task's active form; todo: "☐ pending ✓ done".
    """
    tasks = []
    for path in [p for d in claude_dirs() for p in glob.glob(f"{d}/tasks/{session_id}/*.json")]:
        try:
            with open(path) as fh:
                tasks.append(json.load(fh))
        except (OSError, ValueError):
            continue
    if not tasks:
        return None, None
    tasks.sort(key=lambda t: int(t["id"]) if str(t.get("id", "")).isdigit() else 0)
    current = next((t for t in tasks if t.get("status") == "in_progress"), None)
    doing = None
    if current:
        doing = re.sub(r"[\x00-\x1f\x7f-\x9f]", "", current.get("activeForm") or current.get("subject") or "")
        if len(doing) > DOING_MAX:
            doing = doing[:DOING_MAX - 1] + "…"
        doing = "▶ " + doing
    pending = sum(t.get("status") == "pending" for t in tasks)
    done = sum(t.get("status") == "completed" for t in tasks)
    return doing, (f"☐ {pending} ✓ {done}" if pending or done else None)


def codex_info(session_id):
    files = glob.glob(f"{HOME}/.codex/sessions/**/*{session_id}*.jsonl", recursive=True)
    if not files:
        return None, None
    model = last_match(max(files, key=os.path.getmtime), r'"model":"([^"]+)"')
    return (short_model(model) if model else None), "codex"


def opencode_info(cwd):
    """(model, provider) from opencode's configured default model.

    opencode models are "provider/model" (synapse convention: the provider is
    the gateway, e.g. omniroute/ai-suush-coding), so the provider plays the
    account role. A project opencode.json overrides the user one.
    """
    candidates = [os.path.join(cwd or "", "opencode.json"),
                  os.path.join(os.environ.get("XDG_CONFIG_HOME", f"{HOME}/.config"), "opencode", "opencode.json")]
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


def agent_info(kind, session, cwd=None):
    """(model, account) for any supported agent kind."""
    if kind == "claude" and session:
        return claude_info(session)
    if kind == "codex" and session:
        return codex_info(session)
    if kind in ("opencode", "open_code"):
        return opencode_info(cwd)
    return None, None


STOPWORDS = {"de", "des", "du", "la", "le", "les", "et", "en", "pour", "dans", "un", "une",
             "the", "and", "of", "for", "to", "a", "plus", "claude", "code"}
GENERIC_TITLES = {"", "claude code", "claude", "codex", "opencode"}


def slug(text):
    """ASCII kebab-case, accents folded."""
    import unicodedata
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "-", text).strip("-")


def space_slug(space_label):
    """Name prefix for a space: "Forge-Stack-Workshop" -> "forge", "padam-av" -> "padam-av"."""
    space = "agent"
    for i, part in enumerate(slug(space_label or "").split("-")):
        candidate = part if i == 0 else f"{space}-{part}"
        if i and len(candidate) > 10:
            break
        space = candidate[:10] if i == 0 else candidate
    return space


def theme_name(agent, space_label):
    """<space>-<theme>, e.g. padam-av-eisenhower; valid herdr agent name."""
    space = space_slug(space_label)
    title = (agent.get("terminal_title_stripped") or "").strip()
    words = [w for w in slug(title).split("-") if w and w not in STOPWORDS]
    folder = [w for w in slug(os.path.basename(agent.get("cwd") or "")).split("-")
              if w and w not in space.split("-")]
    if title.lower() in GENERIC_TITLES or not words:
        words = folder or ["main"]
    name = space
    for word in words[:2]:
        if len(f"{name}-{word}") > 28:
            break
        name = f"{name}-{word}"
    if name == space:
        name = f"{space}-{words[0][:27 - len(space)]}"
    if not name[0].isalpha():
        name = "a" + name[:31]
    return name


NAMED_FILE = os.path.join(STATE_DIR, "named.json")


def load_named():
    try:
        with open(NAMED_FILE) as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def is_auto_name(name, space):
    """True when name carries the space prefix auto_rename gives (`<space>-…`).

    herdr restores agent names after a server restart while named.json may not
    know them, and the topic may have changed since; the prefix is what
    tells our names apart from hand-given ones.
    """
    return name == space or name.startswith(space + "-")


def auto_rename(agents, named, workspaces=None):
    """Name every agent after its space and topic, unless the user named it."""
    if workspaces is None:
        workspaces = herdr("workspace", "list").get("result", {}).get("workspaces", [])
    labels = {w["workspace_id"]: w.get("label") for w in workspaces}
    taken = {a.get("name") for a in agents if a.get("name")}
    for agent in agents:
        pane_id, current = agent["pane_id"], agent.get("name")
        wanted = theme_name(agent, labels.get(agent["workspace_id"]))
        space = space_slug(labels.get(agent["workspace_id"]))
        if current and named.get(pane_id) != current and not is_auto_name(current, space):
            continue  # named by hand: leave it
        base, n = wanted, 2
        while wanted in taken and wanted != current:
            wanted = f"{base[:29]}-{n}"
            n += 1
        if wanted != current:
            try:
                herdr("agent", "rename", pane_id, wanted)
            except RuntimeError:
                continue
            taken.discard(current)
            taken.add(wanted)
        named[pane_id] = wanted
    os.makedirs(STATE_DIR, exist_ok=True)
    with open(NAMED_FILE, "w") as fh:
        json.dump(named, fh)


BILLED_DIR = os.path.join(STATE_DIR, "billed")


def is_billed(tokens):
    """True once the plan quota is spent and usage is billed (extra credits).

    usagebar shows "Σ 425k $0.04" on a pay-as-you-go pane and the remaining
    plan window otherwise ("5h 0%" when exhausted).
    """
    text = " ".join(str(tokens.get(k) or "") for k in ("limit", "context"))
    return "$" in text or "Σ" in text or re.search(r"\b\d+[hdw] 0%", text) is not None


def mark_billed(session, billed):
    if not session or not re.fullmatch(r"[A-Za-z0-9-]+", session):
        return
    path = os.path.join(BILLED_DIR, session)
    if billed:
        os.makedirs(BILLED_DIR, exist_ok=True)
        open(path, "w").close()
    elif os.path.exists(path):
        os.remove(path)


def git_summary(cwd):
    """Compact git state: "⑂ main ↑2 ↓1 +3 ~2 ?1", or "⑂ main ✓" when clean."""
    if not cwd:
        return None
    try:
        out = subprocess.run(["git", "-C", cwd, "status", "--porcelain=v2", "--branch"],
                             capture_output=True, text=True, timeout=3)
    except Exception:
        return None
    if out.returncode != 0:
        return None
    branch, ahead, behind, staged, changed, untracked = "?", 0, 0, 0, 0, 0
    for line in out.stdout.splitlines():
        if line.startswith("# branch.head "):
            branch = line.split(" ", 2)[2]
        elif line.startswith("# branch.ab "):
            a, b = line.split()[2:4]
            ahead, behind = int(a), -int(b)
        elif line.startswith(("1 ", "2 ", "u ")):
            xy = line.split()[1]
            staged += xy[0] != "."
            changed += xy[1] != "."
        elif line.startswith("? "):
            untracked += 1
    branch = re.sub(r"[\x00-\x1f\x7f-\x9f]", "", branch)[:20]
    parts = [f"⑂ {branch}"]
    parts += [f"↑{ahead}"] if ahead else []
    parts += [f"↓{behind}"] if behind else []
    parts += [f"+{staged}"] if staged else []
    parts += [f"~{changed}"] if changed else []
    parts += [f"?{untracked}"] if untracked else []
    if len(parts) == 1:
        parts.append("✓")
    return " ".join(parts)


def session_for(agent):
    """Agent session id: herdr's, else the newest one the status line reported
    from this pane (herdr sometimes loses track after a resume)."""
    session = (agent.get("agent_session") or {}).get("value")
    if session:
        return session
    best, best_ts = None, 0
    for path in glob.glob(os.path.join(STATE_DIR, "status", "*.json")):
        try:
            with open(path) as fh:
                data = json.load(fh)
        except (OSError, ValueError):
            continue
        if data.get("pane") == agent.get("pane_id") and data.get("ts", 0) > best_ts:
            best, best_ts = os.path.basename(path)[:-5], data["ts"]
    return best


def subagents_live(session_id, live_s=20):
    """"↳ 2 agents: security-auditor, explore" for subagents writing right now."""
    names = []
    for meta_path in [p for d in claude_dirs() for p in glob.glob(f"{d}/projects/*/{session_id}/subagents/*.meta.json")]:
        try:
            if time.time() - os.path.getmtime(meta_path.replace(".meta.json", ".jsonl")) > live_s:
                continue
            with open(meta_path) as fh:
                names.append(re.sub(r"[\x00-\x1f\x7f-\x9f]", "", json.load(fh).get("agentType") or "agent"))
        except (OSError, ValueError):
            continue
    if not names:
        return None
    return f"↳ {len(names)} subagent{'s' if len(names) > 1 else ''}: " + ", ".join(sorted(set(names)))[:40]


def blocked_transitions(agents, previous):
    """Agents that just entered "blocked" (not already blocked last tick).

    previous maps pane_id -> last seen status and is updated in place; agents
    seen for the first time never notify, so a daemon restart stays quiet.
    """
    fresh = []
    for agent in agents:
        pane_id, status = agent["pane_id"], agent.get("agent_status")
        before = previous.get(pane_id)
        previous[pane_id] = status
        if status == "blocked" and before is not None and before != "blocked":
            fresh.append(agent)
    for gone in set(previous) - {a["pane_id"] for a in agents}:
        del previous[gone]
    return fresh


def notify_blocked(agent, labels, run=subprocess.run):
    """One desktop notification; herdr's own toast when notify-send is missing."""
    name = re.sub(r"[\x00-\x1f\x7f-\x9f]", "", agent.get("name") or agent["pane_id"])
    space = re.sub(r"[\x00-\x1f\x7f-\x9f]", "", labels.get(agent["workspace_id"]) or "")
    title, body = f"‼ {name} attend une réponse", f"space {space}" if space else ""
    try:
        run(["notify-send", "--app-name=herdr", "--urgency=critical", title, body],
            check=True, capture_output=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        run([HERDR, "notification", "show", title, "--body", body, "--sound", "request"],
            check=False, capture_output=True, timeout=5)


def publish(pane_id, tokens):
    args = ["pane", "report-metadata", pane_id, "--source", SOURCE, "--ttl-ms", str(TTL_MS)]
    for name in TOKENS:
        if tokens.get(name):
            args += ["--token", f"{name}={tokens[name]}"]
        else:
            args += ["--clear-token", name]
    herdr(*args)


def tick(shown, snap=None):
    if time.monotonic() - shown.get("_refreshed", 0) > TTL_MS / 1000 / 3:
        # unchanged tokens are not re-sent each round, so force one round
        # before TTL_MS lets herdr drop them
        named, status = shown.get("_named", {}), shown.get("_status", {})
        shown.clear()
        shown["_named"], shown["_status"] = named, status
        shown["_refreshed"] = time.monotonic()
    if snap is None:
        snap = {"agents": herdr("agent", "list").get("result", {}).get("agents", []),
                "workspaces": herdr("workspace", "list").get("result", {}).get("workspaces", [])}
    agents = snap["agents"]
    auto_rename(agents, shown.setdefault("_named", load_named()), snap["workspaces"])
    fresh = blocked_transitions(agents, shown.setdefault("_status", {}))
    if fresh:
        labels = {w["workspace_id"]: w.get("label") for w in snap["workspaces"]}
        for agent in fresh:
            notify_blocked(agent, labels)
    live = set()
    for agent in agents:
        pane_id = agent["pane_id"]
        live.add(pane_id)
        session = session_for(agent)
        kind = agent.get("agent", "")
        model, account = agent_info(kind, session, agent.get("cwd"))
        mark_billed(session, is_billed(agent.get("tokens") or {}))
        doing = todo = None
        subs = None
        if session and kind == "claude":
            doing, todo = claude_tasks(session)
            subs = subagents_live(session)
        git = git_summary(agent.get("foreground_cwd") or agent.get("cwd"))
        tokens = {"model": model, "account": account, "doing": doing, "todo": todo, "git": git, "subs": subs}
        if shown.get(pane_id) != tokens:
            publish(pane_id, tokens)
            shown[pane_id] = tokens
    for gone in set(shown) - live - {"_refreshed", "_named", "_status"}:
        shown.pop(gone, None)


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
    while True:
        if cockpit_daemon_alive():
            break  # the shared cockpit daemon runs this tick now
        try:
            tick(shown)
            failures = 0
        except Exception:
            failures += 1
            if failures >= 3:
                shown.clear()
                time.sleep(10)
        time.sleep(POLL_S)


def running_pid():
    try:
        pid = int(open(PID).read().strip())
        os.kill(pid, 0)
        return pid
    except (OSError, ValueError):
        return None


def cockpit_daemon_alive():
    """chrysa.cockpit's shared daemon runs this tick itself when it is up."""
    lock = os.path.expanduser("~/.local/state/chrysa.cockpit/daemon.lock")
    if not os.path.exists(lock):
        return False
    try:
        with open(lock, "a+") as handle:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            fcntl.flock(handle, fcntl.LOCK_UN)
        return False
    except OSError:
        return True


def ensure():
    if running_pid() or cockpit_daemon_alive():
        return
    os.makedirs(STATE_DIR, exist_ok=True)
    subprocess.Popen([sys.executable, os.path.abspath(__file__), "daemon"],
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL, start_new_session=True)


def stop():
    pid = running_pid()
    if pid:
        os.kill(pid, signal.SIGTERM)
    try:
        for agent in herdr("agent", "list").get("result", {}).get("agents", []):
            publish(agent["pane_id"], {})
    except Exception:
        pass


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "ensure"
    {"ensure": ensure, "daemon": daemon, "stop": stop}.get(cmd, ensure)()


if __name__ == "__main__":
    main()
