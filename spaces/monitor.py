#!/usr/bin/env python3
"""herdr-spaces - readable space rows: agent count, worktrees, per-space color.

Every workspace row gets:
  - a colored agent-count chip (`spN` token, N = the space's stable color slot),
    so at a glance you see how many recognized agents run in that space;
  - a worktree list (`wt` token) whenever the space spans more than one git
    worktree, e.g. "wt main | feat/foo";
and every agent row gets a matching colored dot (`agN` pane token) in the SAME
color slot as its space, so spaces and their agents read as one group.

The color slot is a stable hash of the workspace id, so a space keeps its color
across restarts. Config styles slots 0..7 identically in [ui.sidebar.spaces] and
[ui.sidebar.agents]; the plugin only decides which slot each space/agent lands
in. This mirrors chrysa.rtk-savings: text via metadata, color via pre-styled
variant rows, one populated at a time.

Commands:
  ensure  start the background monitor if not already running (event hooks use this)
  daemon  run the monitor loop in the foreground (spawned by ensure)
  stop    stop the monitor and clear every token it published
"""
import fcntl
import json
import os
import signal
import shutil
import subprocess
import sys
import time
import zlib

PLUGIN_ID = "chrysa.spaces"
SOURCE = f"plugin:{PLUGIN_ID}"

PALETTE_SLOTS = 8  # keep in sync with the spN/agN rows in config.toml
POLL_S = 6  # agent count + worktree set are cheap CLI reads
TTL_MS = POLL_S * 20 * 1000  # tokens outlive a few failed reads, then expire
REFRESH_S = TTL_MS / 1000 / 3  # republish unchanged tokens well before they expire

SP_VARIANTS = tuple(f"sp{i}" for i in range(PALETTE_SLOTS))
AG_VARIANTS = tuple(f"ag{i}" for i in range(PALETTE_SLOTS))


def herdr_bin():
    """Absolute path to the herdr CLI.

    Plugin commands do not inherit the user's login PATH, so a bare "herdr"
    raises FileNotFoundError and the daemon would quit after a few ticks.
    herdr exports HERDR_BIN_PATH from /proc/self/exe, which reads
    "/path/to/herdr (deleted)" after an in-place upgrade - trust it only when
    it actually resolves.
    """
    explicit = os.environ.get("HERDR_BIN_PATH")
    if explicit and os.access(explicit, os.X_OK):
        return explicit
    if explicit and explicit.endswith(" (deleted)"):
        stripped = explicit[: -len(" (deleted)")]
        if os.access(stripped, os.X_OK):
            return stripped
    found = shutil.which("herdr")
    if found:
        return found
    for candidate in ("~/.local/bin/herdr", "/usr/local/bin/herdr",
                      "/opt/homebrew/bin/herdr", "/usr/bin/herdr"):
        path = os.path.expanduser(candidate)
        if os.access(path, os.X_OK):
            return path
    return "herdr"


HERDR = herdr_bin()
SOCKET_PATH = os.environ.get("HERDR_SOCKET_PATH", "")
STATE_DIR = os.environ.get("HERDR_PLUGIN_STATE_DIR") or os.path.expanduser(
    f"~/.local/state/{PLUGIN_ID}")
PIDFILE = os.path.join(STATE_DIR, "monitor.pid")


# ------------------------------------------------------------------- herdr --

def herdr_cli(*args):
    return subprocess.run([HERDR, *args], capture_output=True, text=True, timeout=10)


def herdr_json(*args, key):
    proc = herdr_cli(*args)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or f"herdr {' '.join(args)} failed")
    return json.loads(proc.stdout)["result"][key]


# --------------------------------------------------------------- gathering --

def family(label):
    """Ecosystem a space belongs to: "padam-av-simul" -> "padam-av".

    Spaces whose label extends another space's label (prefix + "-") join that
    space's family, so a project and its satellites share one color.
    """
    return label.lower()


def color_slots(workspaces):
    """workspace_id -> color slot; one slot per family, distinct across families.

    Families are sorted by name and handed slots in order, so colors stay
    stable while the set of families does not change, and two families only
    share a color once there are more than PALETTE_SLOTS of them.
    """
    labels = {w["workspace_id"]: family(w.get("label") or w["workspace_id"]) for w in workspaces}
    roots = sorted(set(labels.values()), key=len)
    root_of = {}
    for name in sorted(set(labels.values())):
        root_of[name] = next((r for r in roots if name == r or name.startswith(r + "-")), name)
    order = sorted(set(root_of.values()))
    slot_of = {root: i % PALETTE_SLOTS for i, root in enumerate(order)}
    return {ws_id: slot_of[root_of[name]] for ws_id, name in labels.items()}


def git_info(cwd):
    """(common_dir, toplevel, branch) for a cwd in a git work tree, else None.

    All work trees of ONE repo share a common git dir but have distinct
    toplevels - that shared common dir is how we tell "several worktrees of the
    same repo" apart from "several unrelated repos in the same space".
    """
    try:
        proc = subprocess.run(
            ["git", "-C", cwd, "rev-parse",
             "--git-common-dir", "--show-toplevel", "--abbrev-ref", "HEAD"],
            capture_output=True, text=True, timeout=5)
    except Exception:
        return None
    if proc.returncode != 0:
        return None
    lines = proc.stdout.split("\n")
    if len(lines) < 3 or not lines[1]:
        return None
    common = os.path.realpath(os.path.join(cwd, lines[0])) if lines[0] else lines[0]
    return common, lines[1], (lines[2] or "detached")


def worktree_count(toplevel):
    """Number of work trees git knows for the repo checked out at toplevel."""
    try:
        proc = subprocess.run(["git", "-C", toplevel, "worktree", "list", "--porcelain"],
                              capture_output=True, text=True, timeout=5)
    except Exception:
        return 0
    return proc.stdout.count("\nworktree ") + proc.stdout.startswith("worktree ")


def worktrees_for(cwds, cache):
    """Branch labels when this space holds >1 worktree of a single repo.

    Empty unless some repo (common git dir) is checked out in more than one
    work tree here; several unrelated repos are just a multi-project space.
    """
    repos = {}  # common_dir -> {toplevel: branch}
    for cwd in cwds:
        if cwd not in cache:
            cache[cwd] = git_info(cwd)
        info = cache[cwd]
        if info:
            common, top, branch = info
            repos.setdefault(common, {}).setdefault(top, branch)
    labels = []
    if all(len(trees) <= 1 for trees in repos.values()):
        # nothing open side by side: still surface repos that own extra
        # worktrees on disk, as a count
        for common, trees in repos.items():
            count = cache.setdefault(("wt", common), worktree_count(next(iter(trees))))
            if count > 1:
                labels.append((os.path.basename(next(iter(trees))), count))
        if len(labels) == 1:
            return [f"{labels[0][1]}"]  # one repo: the space name says which
        return [f"{name}·{count}" for name, count in labels]
    for trees in repos.values():
        if len(trees) > 1:
            for top, branch in trees.items():
                # disambiguate same-branch worktrees by their directory name
                labels.append(branch if list(trees.values()).count(branch) == 1
                              else f"{branch}·{os.path.basename(top)}")
    return labels


def gather(cache):
    """workspace_id -> {slot, agents, worktrees[]} plus pane_slot per agent pane."""
    panes = herdr_json("pane", "list", key="panes")
    agents = herdr_json("agent", "list", key="agents")
    slots = color_slots(herdr_json("workspace", "list", key="workspaces"))

    def color_slot(ws_id):
        return slots.get(ws_id, zlib.crc32(ws_id.encode()) % PALETTE_SLOTS)

    cwds_by_ws = {}
    for pane in panes:
        cwd = pane.get("cwd") or pane.get("foreground_cwd")
        if cwd:
            cwds_by_ws.setdefault(pane["workspace_id"], []).append(cwd)

    agent_count = {}
    pane_slot = {}  # pane_id -> color slot, for the agent panel
    for agent in agents:
        ws_id = agent["workspace_id"]
        agent_count[ws_id] = agent_count.get(ws_id, 0) + 1
        pane_slot[agent["pane_id"]] = color_slot(ws_id)

    spaces = {}
    for ws_id, cwds in cwds_by_ws.items():
        spaces[ws_id] = {
            "slot": color_slot(ws_id),
            "agents": agent_count.get(ws_id, 0),
            "worktrees": worktrees_for(cwds, cache),
        }
    # spaces with panes but no agents still deserve their (0-agent) chip
    for ws_id in agent_count:
        spaces.setdefault(ws_id, {"slot": color_slot(ws_id),
                                  "agents": agent_count[ws_id], "worktrees": []})
    return spaces, pane_slot


# --------------------------------------------------------------- rendering --

def render_space(info):
    """{token: text} for one space's chip + optional worktree list."""
    tokens = {SP_VARIANTS[info["slot"]]: f"◉ {info['agents']}"}
    if info["worktrees"]:
        tokens["wt"] = "⑂" + " ".join(info["worktrees"])
    return tokens


# ---------------------------------------------------------------- publish --

def report(scope, target_id, tokens, all_variants, extra_clear=()):
    """Publish `tokens` and clear every other managed token in one CLI call."""
    args = [scope, "report-metadata", target_id, "--source", SOURCE,
            "--ttl-ms", str(TTL_MS)]
    for name, text in tokens.items():
        args += ["--token", f"{name}={text}"]
    for name in list(all_variants) + list(extra_clear):
        if name not in tokens:
            args += ["--clear-token", name]
    herdr_cli(*args)


def clear_space(ws_id):
    report("workspace", ws_id, {}, SP_VARIANTS, extra_clear=("wt",))


def clear_pane(pane_id):
    report("pane", pane_id, {}, AG_VARIANTS)


def publish_round(state):
    """One refresh pass. state carries what each target currently shows."""
    spaces, pane_slot = gather(state["cache"])
    if time.monotonic() - state.get("refreshed", 0) > REFRESH_S:
        # unchanged tokens are not re-sent each round, so force one round
        # before TTL_MS lets herdr drop them
        state["ws"].clear()
        state["pane"].clear()
        state["cache"].clear()
        state["refreshed"] = time.monotonic()

    # spaces
    seen_ws = set(spaces)
    for ws_id, info in spaces.items():
        tokens = render_space(info)
        if state["ws"].get(ws_id) != tokens:
            report("workspace", ws_id, tokens, SP_VARIANTS, extra_clear=("wt",))
            state["ws"][ws_id] = tokens
    for ws_id in list(state["ws"]):
        if ws_id not in seen_ws:
            clear_space(ws_id)
            del state["ws"][ws_id]

    # agent panes
    for pane_id, slot in pane_slot.items():
        token = {AG_VARIANTS[slot]: "●"}
        if state["pane"].get(pane_id) != token:
            report("pane", pane_id, token, AG_VARIANTS)
            state["pane"][pane_id] = token
    for pane_id in list(state["pane"]):
        if pane_id not in pane_slot:
            clear_pane(pane_id)
            del state["pane"][pane_id]


# ------------------------------------------------------------------ daemon --

def running_pid():
    try:
        return int(open(PIDFILE).read().strip())
    except Exception:
        return None


def daemon_alive():
    """True when a monitor holds the pidfile lock (the lock, not the pid, is
    authoritative: pids recycle fast enough to alias an unrelated process)."""
    if not os.path.exists(PIDFILE):
        return False
    try:
        with open(PIDFILE, "a+") as handle:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            fcntl.flock(handle, fcntl.LOCK_UN)
        return False
    except OSError:
        return True


def claim_pidfile():
    """Exclusive daemon slot, or None when another daemon holds it."""
    os.makedirs(STATE_DIR, exist_ok=True)
    handle = open(PIDFILE, "a+")
    try:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        handle.close()
        return None
    handle.seek(0)
    handle.truncate()
    handle.write(str(os.getpid()))
    handle.flush()
    return handle


def cmd_ensure():
    if daemon_alive():
        return
    os.makedirs(STATE_DIR, exist_ok=True)
    subprocess.Popen(
        [sys.executable, os.path.abspath(__file__), "daemon"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        start_new_session=True,
    )


def cmd_daemon():
    lock = claim_pidfile()
    if not lock:
        return
    state = {"ws": {}, "pane": {}, "cache": {}}
    failures = 0
    socket_misses = 0
    while True:
        if SOCKET_PATH and not os.path.exists(SOCKET_PATH):
            socket_misses += 1
            if socket_misses >= 3:
                break
            time.sleep(10)
            continue
        socket_misses = 0
        try:
            publish_round(state)
            failures = 0
        except Exception:
            failures += 1
            if failures >= 3:
                break
            time.sleep(10)
            continue
        time.sleep(POLL_S)
    lock.close()
    try:
        os.remove(PIDFILE)
    except OSError:
        pass


def cmd_stop():
    pid = running_pid() if daemon_alive() else None
    if pid:
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            pass
    try:
        for workspace in herdr_json("workspace", "list", key="workspaces"):
            clear_space(workspace["workspace_id"])
    except Exception:
        pass
    try:
        for pane in herdr_json("pane", "list", key="panes"):
            clear_pane(pane["pane_id"])
    except Exception:
        pass
    try:
        os.remove(PIDFILE)
    except OSError:
        pass


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "ensure"
    if cmd == "ensure":
        cmd_ensure()
    elif cmd == "daemon":
        try:
            cmd_daemon()
        except KeyboardInterrupt:
            pass
    elif cmd == "stop":
        cmd_stop()
    else:
        sys.stderr.write(f"unknown command: {cmd}\n")
        sys.exit(2)


if __name__ == "__main__":
    main()
