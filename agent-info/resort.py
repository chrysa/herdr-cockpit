#!/usr/bin/env python3
"""Sort the sidebar spaces now: the agent-info tree order, applied with workspace.move.

Bound to a herdr key (cockpit config); the daemon does the same on every tick. Prints each
move that herdr refused to stderr and reports the count in a toast.
Usage: resort.py
"""
import sys

import monitor


def layout():
    """(ids in herdr order, wanted order) for the sidebar, as monitor.tick builds them."""
    workspaces = monitor.herdr("workspace", "list").get("result", {}).get("workspaces", [])
    panes = monitor.herdr("pane", "list").get("result", {}).get("panes", [])
    labels = [monitor.CONTROL.sub("", w.get("label") or "") for w in workspaces]
    folders = monitor.space_folders(workspaces, panes)
    listed = [(w["workspace_id"], label, folders.get(w["workspace_id"]))
              for w, label in zip(workspaces, labels) if w.get("workspace_id")]
    listed, parents = monitor.worktree_spaces(listed)
    groups = monitor.sibling_groups(listed, parents)
    order, _, _ = monitor.space_tree(listed, parents, groups)
    return [ws for ws, _, _ in listed], order


def main():
    ids, wanted = layout()
    pending = len(monitor.moves_to(ids, wanted))
    monitor.group_spaces(ids, wanted, {})
    after, _ = layout()
    left = len(monitor.moves_to(after, wanted))
    text = f"Spaces triés · {pending} déplacement(s), {left} restant(s)"
    try:
        monitor.request("notification.show", {"title": text})
    except (OSError, RuntimeError):
        print(text, file=sys.stderr)
    return 1 if left else 0


if __name__ == "__main__":
    sys.exit(main())
