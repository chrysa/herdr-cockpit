#!/usr/bin/env python3
"""Services pane: containers and listening processes of the tab's git project.

The only part of the former info panel with no native or plugin equivalent.
Conversation, subagents and to-dos come from flowy11/agent-panel; usage from
usagebar; RTK from chrysa.rtk-savings; workspace overview from herdr's Go To.
"""
import os
import re
import shutil
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import monitor  # noqa: E402
import services  # noqa: E402

REFRESH_S = 2
CONTROL = re.compile(r"[\x00-\x1f\x7f-\x9f]")
HOME = os.path.realpath(os.path.expanduser("~"))
C = {"ok": "\033[32m", "warn": "\033[31m", "dim": "\033[2m", "url": "\033[34m", "b": "\033[1m", "r": "\033[0m"}
STYLE = {"running": "ok", "restarting": "warn", "exited": "dim", "dead": "warn"}


def safe(text):
    return CONTROL.sub("", str(text or ""))


def project_root(cwd):
    """Git work tree of an absolute directory under the home directory, or None."""
    path = os.path.realpath(cwd or "")
    if not path.startswith(HOME + os.sep) or not os.path.isdir(path):
        return None
    out = subprocess.run(["git", "--no-optional-locks", "-C", path, "rev-parse", "--show-toplevel"],
                         capture_output=True, text=True, timeout=3)
    return out.stdout.strip() if out.returncode == 0 and out.stdout.strip() else None


def tab_directory():
    """Directory of the agent in this pane's tab (its shell cwd when no agent)."""
    tab, me = os.environ.get("HERDR_TAB_ID"), os.environ.get("HERDR_PANE_ID")
    panes = monitor.herdr("pane", "list").get("result", {}).get("panes", [])
    mine = [p for p in panes if p.get("tab_id") == tab and p.get("pane_id") != me]
    chosen = next((p for p in mine if p.get("agent")), mine[0] if mine else None)
    return (chosen or {}).get("foreground_cwd") or (chosen or {}).get("cwd")


def render(width):
    root = project_root(tab_directory())
    if not root:
        return [f"{C['dim']}Pas de dépôt git dans cet onglet{C['r']}"]
    boxes, procs = services.services(root)
    lines = [f"{C['b']}Services · {safe(os.path.basename(root))}{C['r']}", ""]
    rows = [(STYLE.get(b["state"], "dim"), safe(b["name"]), safe(b["status"]), b["urls"]) for b in boxes]
    rows += [("ok", safe(p["name"]), f"pid {p['pid']}", [p["url"]]) for p in procs]
    if not rows:
        return lines + [f"{C['dim']}aucun conteneur ni port en écoute{C['r']}"]
    name_w = min(max(len(r[1]) for r in rows), width // 3)
    for style, name, status, urls in rows:
        lines.append(f"{C[style]}●{C['r']} {name[:name_w].ljust(name_w)}  {C['dim']}{status}{C['r']}")
        lines += [f"    {C['url']}{safe(u)[:width - 6]}{C['r']}" for u in urls]
    return lines


def main():
    services.docker_snapshot()
    services.ss_snapshot()
    sys.stdout.write("\033[?25l")
    try:
        while True:
            width = shutil.get_terminal_size((40, 20)).columns
            try:
                lines = render(width)
            except Exception as exc:  # keep the pane alive across server hiccups
                lines = [f"{C['dim']}herdr indisponible : {safe(exc)}{C['r']}"]
            sys.stdout.write("\033[H\033[2J" + "\n".join(lines))
            sys.stdout.flush()
            time.sleep(REFRESH_S)
    except KeyboardInterrupt:
        pass
    finally:
        sys.stdout.write("\033[?25h")


if __name__ == "__main__":
    main()
