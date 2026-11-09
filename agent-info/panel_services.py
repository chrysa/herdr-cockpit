#!/usr/bin/python3 -I
"""Services of the agent's project for agent-panel's Apps tab (chrysa fork).

agent-panel runs it as `panel_services.py <cwd> <provider> <session id> <agent pane id>`
(its services-command, written by cockpit setup) and lists one service per line:
<up|down> TAB <name> TAB <url>. Same sources as the header: the monitor's docker and ss
snapshots, so this stays fast.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import header


def rows(cwd):
    root, _ = header.git_state(cwd)
    if not root:
        return []
    return [f"{'up' if up else 'down'}\t{header.safe(name)}\t{header.safe(url)}"
            for name, url, up in header.service_items(root)]


def main():
    cwd = (sys.argv[1:2] or [""])[0]
    if os.path.isdir(cwd):
        print("\n".join(rows(cwd)))


if __name__ == "__main__":
    main()
