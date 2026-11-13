#!/usr/bin/env python3
"""Native shell panes: herdr panes with no AI agent, one line each.

Reads `herdr pane list` and `herdr workspace list` (local socket only).
Usage: shells.py [--json]
"""
import json
import os
import re
import subprocess
import sys

CONTROL = re.compile(r"[\x00-\x1f\x7f]")


def herdr(*args):
    out = subprocess.run([os.environ.get("HERDR_BIN_PATH", "herdr"), *args],
                         capture_output=True, text=True, timeout=10, check=True).stdout
    return json.loads(out).get("result", {})


def shell_rows(panes, workspaces):
    labels = {w.get("workspace_id"): CONTROL.sub("", w.get("label") or "") for w in workspaces}
    rows = []
    for pane in panes:
        if pane.get("agent"):
            continue
        rows.append({
            "pane_id": pane.get("pane_id"),
            "space": labels.get(pane.get("workspace_id"), ""),
            "cwd": CONTROL.sub("", pane.get("foreground_cwd") or pane.get("cwd") or ""),
            "title": CONTROL.sub("", pane.get("terminal_title") or ""),
        })
    return sorted(rows, key=lambda r: (r["space"], r["cwd"]))


def main():
    rows = shell_rows(herdr("pane", "list").get("panes", []), herdr("workspace", "list").get("workspaces", []))
    if "--json" in sys.argv:
        print(json.dumps(rows, ensure_ascii=False, indent=2))
        return
    for r in rows:
        print(f"{r['space']:<24} {r['pane_id']:<12} {r['cwd']}  {r['title']}".rstrip())


if __name__ == "__main__":
    main()
