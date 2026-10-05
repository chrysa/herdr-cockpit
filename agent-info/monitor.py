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
TOKENS = ("model", "account", "doing", "todo")
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


def theme_name(agent, space_label):
    """<space>-<theme>, e.g. padam-av-eisenhower; valid herdr agent name."""
    space = "agent"
    for i, part in enumerate(slug(space_label or "").split("-")):
        candidate = part if i == 0 else f"{space}-{part}"
        if i and len(candidate) > 10:
            break
        space = candidate[:10] if i == 0 else candidate
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


def auto_rename(agents, named):
    """Name every agent after its space and topic, unless the user named it."""
    labels = {w["workspace_id"]: w.get("label") for w in
              herdr("workspace", "list").get("result", {}).get("workspaces", [])}
    taken = {a.get("name") for a in agents if a.get("name")}
    for agent in agents:
        pane_id, current = agent["pane_id"], agent.get("name")
        if current and named.get(pane_id) != current:
            continue  # named by hand: leave it
        wanted = theme_name(agent, labels.get(agent["workspace_id"]))
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


def publish(pane_id, tokens):
    args = ["pane", "report-metadata", pane_id, "--source", SOURCE, "--ttl-ms", str(TTL_MS)]
    for name in TOKENS:
        if tokens.get(name):
            args += ["--token", f"{name}={tokens[name]}"]
        else:
            args += ["--clear-token", name]
    herdr(*args)


def tick(shown):
    if time.monotonic() - shown.get("_refreshed", 0) > TTL_MS / 1000 / 3:
        # unchanged tokens are not re-sent each round, so force one round
        # before TTL_MS lets herdr drop them
        named = shown.get("_named", {})
        shown.clear()
        shown["_named"] = named
        shown["_refreshed"] = time.monotonic()
    agents = herdr("agent", "list").get("result", {}).get("agents", [])
    auto_rename(agents, shown.setdefault("_named", load_named()))
    live = set()
    for agent in agents:
        pane_id = agent["pane_id"]
        live.add(pane_id)
        session = (agent.get("agent_session") or {}).get("value")
        kind = agent.get("agent", "")
        model, account = agent_info(kind, session, agent.get("cwd"))
        mark_billed(session, is_billed(agent.get("tokens") or {}))
        doing = todo = None
        if session and kind == "claude":
            doing, todo = claude_tasks(session)
        tokens = {"model": model, "account": account, "doing": doing, "todo": todo}
        if shown.get(pane_id) != tokens:
            publish(pane_id, tokens)
            shown[pane_id] = tokens
    for gone in set(shown) - live - {"_refreshed", "_named"}:
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


def ensure():
    if running_pid():
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
