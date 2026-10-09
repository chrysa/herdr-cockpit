#!/usr/bin/env python3
"""Filters for herdr's native Agents column, through `agent.view.set`.

Three independent filters, combined with "all":
- profile: the Claude account an agent runs on (`$account` token from
  chrysa.agent-info), cycled through the accounts currently seen;
- active: only agents working or blocked;
- space: only agents of the space selected in herdr.
State lives in the plugin state dir and is re-applied at startup, since herdr
drops the view when the server exits.

Usage: agent_view.py profile | active | space | sort | reset | apply
"""
import json
import os
import socket
import sys

SOURCE = "plugin:chrysa.cockpit"
STATE_DIR = os.environ.get("HERDR_PLUGIN_STATE_DIR") or os.path.expanduser("~/.local/state/chrysa.cockpit")
STATE = os.path.join(STATE_DIR, "agent-view.json")
DEFAULT = {"profile": "", "active": False, "space": False, "attention": False}


def call(method, params):
    path = os.environ.get("HERDR_SOCKET_PATH") or os.path.expanduser("~/.config/herdr/herdr.sock")
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
    if not clauses:
        return None
    return clauses[0] if len(clauses) == 1 else {"op": "all", "filters": clauses}


def label(state):
    parts = [state["profile"] or "tous profils"]
    parts += ["tri attention"] if state.get("attention") else []
    parts += ["actifs"] if state["active"] else []
    parts += ["space courant"] if state["space"] else []
    return " · ".join(parts)


def accounts():
    """Accounts currently reported on agents, sorted ("" first = every profile)."""
    agents = call("agent.list", {}).get("result", {}).get("agents", [])
    found = {(a.get("tokens") or {}).get("account") for a in agents}
    return [""] + sorted(a for a in found if a)


SORT_ATTENTION = [{"field": "attention", "order": "desc"}, {"field": "state_change_seq", "order": "desc"}]


def apply(state):
    query = build_filter(state)
    if query is None and not state.get("attention"):
        return call("agent.view.clear", {"source": SOURCE})
    params = {"source": SOURCE, "label": label(state),
              "filter": query or {"op": "exists", "field": "pane_id"}}
    if state.get("attention"):
        params["sort"] = SORT_ATTENTION
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
    elif command == "reset":
        state = dict(DEFAULT)
    if command != "apply":
        save(state)
    apply(state)
    if command != "apply":
        notify(state)


if __name__ == "__main__":
    main()
