#!/usr/bin/env python3
"""Filters for herdr's native Agents column, through `agent.view.set`.

Three independent filters, combined with "all":
- profile: the Claude account an agent runs on (`$account` token from
  chrysa.agent-info), cycled through the accounts currently seen;
- active: only agents working or blocked;
- space: only agents of the space selected in herdr (on by default, so the
  column follows the selected space; `reset` shows every agent);
- collapsed: agents of the spaces folded by `collapse` (a toggle per space)
  are hidden from the column; the space rows stay in the sidebar.
State lives in the plugin state dir and is re-applied at startup, since herdr
drops the view when the server exits.

Usage: agent_view.py profile | active | space | collapse | attention | sort | reset | apply
"""
import json
import os
import socket
import sys
import time

SOURCE = "plugin:chrysa.cockpit"
STATE_DIR = os.environ.get("HERDR_PLUGIN_STATE_DIR") or os.path.expanduser("~/.local/state/chrysa.cockpit")
STATE = os.path.join(STATE_DIR, "agent-view.json")
NONE = {"profile": "", "active": False, "space": False, "attention": False, "collapsed": []}
# State before any key is pressed: the selected space, in herdr's "priority"
# order (an active view replaces herdr's own sort, so the view carries it).
DEFAULT = {**NONE, "space": True, "attention": True}


def socket_path():
    return os.environ.get("HERDR_SOCKET_PATH") or os.path.expanduser("~/.config/herdr/herdr.sock")


# herdr drops agent views when its server exits. The space-switch hook re-applies
# the view only when the server changed since the last apply (a new server makes a
# new socket file): setting a view resets the Agents column, selection included,
# so it must not happen on every switch.
SERVER_MARK = os.path.join(STATE_DIR, "applied-server")


def server_id():
    try:
        st = os.stat(socket_path())
    except OSError:
        return ""
    return f"{st.st_ino}:{st.st_mtime_ns}"


def remember_server():
    os.makedirs(os.path.dirname(SERVER_MARK), exist_ok=True)
    with open(SERVER_MARK, "w") as fh:
        fh.write(server_id())


def server_changed():
    try:
        with open(SERVER_MARK) as fh:
            return fh.read().strip() != server_id()
    except OSError:
        return True


def call(method, params):
    path = socket_path()
    with socket.socket(socket.AF_UNIX) as sock:
        sock.settimeout(5)
        sock.connect(path)
        sock.sendall((json.dumps({"id": "agent-view", "method": method, "params": params}) + "\n").encode())
        buf = b""
        while not buf.endswith(b"\n"):
            chunk = sock.recv(65536)
            if not chunk:
                break
            buf += chunk
    return json.loads(buf or b"{}")


def load():
    try:
        with open(STATE) as fh:
            return {**DEFAULT, **json.load(fh)}
    except (OSError, ValueError):
        return dict(DEFAULT)


def save(state):
    os.makedirs(STATE_DIR, exist_ok=True)
    with open(STATE, "w") as fh:
        json.dump(state, fh)


def build_filter(state):
    """The agent.view.set filter for a state, or None when nothing is filtered."""
    clauses = []
    if state["profile"]:
        clauses.append({"op": "eq", "field": {"token": "account"}, "value": state["profile"]})
    if state["active"]:
        clauses.append({"op": "in", "field": "status", "values": ["working", "blocked"]})
    if state["space"]:
        clauses.append({"op": "eq", "field": "workspace_id", "value": {"context": "current_workspace_id"}})
    if state.get("collapsed"):
        clauses.append({"op": "not", "filter": {"op": "in", "field": "workspace_id", "values": list(state["collapsed"])}})
    if not clauses:
        return None
    return clauses[0] if len(clauses) == 1 else {"op": "all", "filters": clauses}


def label(state):
    """Short: herdr draws it over the Agents header and cuts the title when long."""
    parts = [state["profile"]] if state["profile"] else []
    parts += ["actifs"] if state["active"] else []
    parts += ["ce space"] if state["space"] else []
    parts += ["priorité"] if state.get("attention") else []
    parts += [f"{len(state['collapsed'])} replié(s)"] if state.get("collapsed") else []
    return " · ".join(parts) or "tous"


def focused_workspace_id():
    spaces = call("workspace.list", {}).get("result", {}).get("workspaces", [])
    return next((w.get("workspace_id") for w in spaces if w.get("focused")), None)


def focus_attention():
    """Focus the first agent waiting on you in the focused space (blocked, else none)."""
    spaces = call("workspace.list", {}).get("result", {}).get("workspaces", [])
    space = next((w.get("workspace_id") for w in spaces if w.get("focused")), None)
    agents = call("agent.list", {}).get("result", {}).get("agents", [])
    waiting = [a for a in agents if a.get("status") == "blocked" and a.get("workspace_id") == space]
    if not waiting:
        return notify_text("Aucun agent en attente dans ce space")
    waiting.sort(key=lambda a: a.get("state_change_seq") or 0, reverse=True)
    call("agent.focus", {"pane_id": waiting[0]["pane_id"]})


def notify_text(text):
    call("notification.show", {"title": text})


def accounts():
    """Accounts currently reported on agents, sorted ("" first = every profile)."""
    agents = call("agent.list", {}).get("result", {}).get("agents", [])
    found = {(a.get("tokens") or {}).get("account") for a in agents}
    return [""] + sorted(a for a in found if a)


# herdr's two native orders ("priority" = attention queue, "spaces" = layout
# order), given explicitly because an active view drops herdr's own sort.
SORT_ATTENTION = [{"field": "attention", "order": "desc"}, {"field": "state_change_seq", "order": "desc"}]
SORT_SPACES = [{"field": "workspace_order"}, {"field": "tab_order"}, {"field": "pane_order"}]


def apply(state):
    query = build_filter(state)
    if query is None and not state.get("attention"):
        return call("agent.view.clear", {"source": SOURCE})
    params = {"source": SOURCE, "label": label(state),
              "filter": query or {"op": "exists", "field": "pane_id"},
              "sort": SORT_ATTENTION if state.get("attention") else SORT_SPACES}
    return call("agent.view.set", params)


def notify(state):
    call("notification.show", {"title": "Agents : " + label(state)})


def main():
    command = sys.argv[1] if len(sys.argv) > 1 else "apply"
    state = load()
    if command == "profile":
        order = accounts()
        state["profile"] = order[(order.index(state["profile"]) + 1) % len(order)] if state["profile"] in order else ""
    elif command == "sort":
        state["attention"] = not state.get("attention")
    elif command in ("active", "space"):
        state[command] = not state[command]
    elif command == "collapse":
        space = focused_workspace_id()
        folded = state.get("collapsed", [])
        if space:
            state["collapsed"] = [s for s in folded if s != space] if space in folded else folded + [space]
    elif command == "attention":
        return focus_attention()
    elif command == "reset":
        state = dict(NONE)
    if command == "refresh":  # space switch: only after a server restart
        if not server_changed():
            return
        command = "apply"
    if command != "apply":
        save(state)
    apply_when_ready(state) if command == "apply" else apply(state)
    remember_server()
    if command != "apply":
        notify(state)


def apply_when_ready(state, wait_s=10.0, step_s=0.5, sleep=time.sleep):
    """apply(), retried while the herdr socket is not up yet (server just starting)."""
    deadline = time.monotonic() + wait_s
    while True:
        try:
            return apply(state)
        except OSError:
            if time.monotonic() >= deadline:
                raise
            sleep(step_s)


if __name__ == "__main__":
    main()
