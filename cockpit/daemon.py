#!/usr/bin/env python3
"""One poller for the whole cockpit.

Each tick reads herdr once (panes, agents, workspaces) and hands that snapshot
to every renderer (chrysa.spaces, chrysa.agent-info), instead of each plugin
polling herdr on its own. While this daemon holds its lock, the plugins' own
`ensure` stays idle; standalone daemons found running are stopped at start.

Commands: ensure (start in the background if needed), daemon (foreground), stop.
"""
import fcntl
import importlib.util
import os
import signal
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATE = os.path.expanduser("~/.local/state/chrysa.cockpit")
LOCK = os.path.join(STATE, "daemon.lock")
PID = os.path.join(STATE, "daemon.pid")
POLL_S = 6


def load(name, relpath):
    """Import a plugin's monitor.py under its own name (both files are monitor.py)."""
    path = os.path.join(ROOT, relpath)
    sys.path.insert(0, os.path.dirname(path))
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    sys.path.pop(0)
    return module


def stop_standalone(modules):
    """SIGTERM the per-plugin daemons so herdr is not polled twice."""
    for module in modules:
        pid = module.running_pid()
        if pid and pid != os.getpid():
            try:
                os.kill(pid, signal.SIGTERM)
            except OSError:
                pass


def run_tick(snapshot, renderers):
    """Call each renderer with the same snapshot; one failing does not stop the others.

    Returns the names of renderers that raised.
    """
    failed = []
    for name, render in renderers:
        try:
            render(snapshot)
        except Exception:
            failed.append(name)
    return failed


def daemon():
    os.makedirs(STATE, exist_ok=True)
    lock = open(LOCK, "a+")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return
    with open(PID, "w") as fh:
        fh.write(str(os.getpid()))
    spaces = load("cockpit_spaces", "spaces/monitor.py")
    agent_info = load("cockpit_agent_info", "agent-info/monitor.py")
    stop_standalone([spaces, agent_info])
    spaces_state = {"ws": {}, "pane": {}, "cache": {}}
    shown = {}
    renderers = [("spaces", lambda snap: spaces.publish_round(spaces_state, snap)),
                 ("agent-info", lambda snap: agent_info.tick(shown, snap))]
    misses = 0
    while True:
        try:
            snap = spaces.snapshot()
            misses = 0
        except Exception:
            misses += 1
            if misses >= 10:  # server gone for a minute: exit, startup hook restarts us
                break
            time.sleep(POLL_S)
            continue
        run_tick(snap, renderers)
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
    os.makedirs(STATE, exist_ok=True)
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
