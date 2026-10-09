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

Commands: ensure (start in the background if needed), daemon, stop.
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
REFRESH_S = TTL_MS / 1000 / 3  # republish unchanged tokens before herdr expires them
TAIL_BYTES = 256 * 1024
TOKENS = ("account", "model")
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


def tick(shown):
    if time.monotonic() - shown.get("_refreshed", 0) > REFRESH_S:
        shown.clear()
        shown["_refreshed"] = time.monotonic()
    agents = herdr("agent", "list").get("result", {}).get("agents", [])
    for agent in agents:
        model, account = agent_info(agent)
        tokens = {"account": account, "model": model}
        if shown.get(agent["pane_id"]) != tokens:
            publish(agent["pane_id"], tokens)
            shown[agent["pane_id"]] = tokens
    live = {a["pane_id"] for a in agents}
    for gone in set(shown) - live - {"_refreshed"}:
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
    while failures < 10:
        try:
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
    subprocess.Popen([sys.executable, os.path.abspath(__file__), "daemon"],
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL, start_new_session=True)


def stop():
    pid = running_pid()
    if pid:
        os.kill(pid, signal.SIGTERM)


def main():
    {"ensure": ensure, "daemon": daemon, "stop": stop}.get(sys.argv[1] if len(sys.argv) > 1 else "ensure", ensure)()


if __name__ == "__main__":
    main()
