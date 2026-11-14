"""Git worktrees opened as herdr worktree workspaces.

A pane whose directory is a linked git worktree (not the main checkout) is opened once
with `herdr worktree open --cwd <checkout>`, so herdr groups it with its repository like
its own worktrees. Paths herdr already lists are skipped; a path is tried once per run
of the daemon (AGENT_INFO_WORKTREES=0 turns it off).
"""

import os
import subprocess

ENABLED = os.environ.get("AGENT_INFO_WORKTREES", "1") != "0"


def checkout_of(path):
    """Top of the linked worktree holding path, or None (main checkout, not a repo, error)."""
    try:
        out = subprocess.run(["git", "-C", path, "rev-parse", "--path-format=absolute",
                              "--git-dir", "--git-common-dir", "--show-toplevel"],
                             capture_output=True, text=True, timeout=5, check=True).stdout.split("\n")
    except (OSError, subprocess.SubprocessError):
        return None
    if len(out) < 3:
        return None
    git_dir, common, top = (os.path.realpath(p) for p in out[:3])
    return top if git_dir != common else None


def listed_paths(node, found=None):
    """Every string in a herdr reply that names a path (checkout_path, path, cwd...)."""
    found = set() if found is None else found
    if isinstance(node, dict):
        for value in node.values():
            listed_paths(value, found)
    elif isinstance(node, list):
        for value in node:
            listed_paths(value, found)
    elif isinstance(node, str) and node.startswith("/"):
        found.add(os.path.realpath(node))
    return found


def open_linked(panes, herdr, state):
    """Open each linked worktree pane's checkout that herdr does not list yet."""
    if not ENABLED:
        return
    attempted = state.setdefault("worktrees_tried", [])
    known = listed_paths(herdr("worktree", "list"))
    for pane in panes:
        path = pane.get("foreground_cwd") or pane.get("cwd")
        if not path or not os.path.isdir(path):
            continue
        top = checkout_of(path)
        if not top or top in known or top in attempted:
            continue
        attempted.append(top)
        herdr("worktree", "open", "--cwd", top)
    del attempted[:-200]  # bounded memory


WORKTREE_MARK = "⎇"  # branch glyph: a worktree space is named by its branch, under its repository


def worktree_of(path):
    """(main checkout top, branch) for a linked worktree at path, else None."""
    top = checkout_of(path)
    if not top:
        return None
    try:
        out = subprocess.run(["git", "-C", top, "rev-parse", "--path-format=absolute", "--git-common-dir",
                              "--abbrev-ref", "HEAD"], capture_output=True, text=True, timeout=5, check=True).stdout.split("\n")
    except (OSError, subprocess.SubprocessError):
        return None
    common, branch = os.path.realpath(out[0]), (out[1] if len(out) > 1 else "")
    if not branch or branch == "HEAD":
        return None
    return os.path.dirname(common), branch
