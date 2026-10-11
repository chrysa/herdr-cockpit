#!/usr/bin/python3 -I
"""Header lines for agent-panel (chrysa fork): what the Claude status line shows.

agent-panel runs it as `header.py <cwd> <provider> <session id> <agent pane id>`
and shows its output above the tab bar: account and model, the full folder, the git
branch and state, then the project's containers and listeners with their URLs.
Docker and ss outputs come from the agent-info monitor, so this stays fast.
"""
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import monitor  # noqa: E402
import services  # noqa: E402

HOME = os.path.expanduser("~")
MAX_SERVICES = 3
ACCOUNT = {"perso": "38;2;249;226;175", "pro": "38;2;137;220;235", "codex": "38;2;166;227;161"}
DIM, MAUVE, BLUE, GREEN, YELLOW, SKY, RESET = ("\033[2m", "\033[38;2;203;166;247m", "\033[38;2;137;180;250m",
                                               "\033[32m", "\033[33m", "\033[38;2;137;220;235m", "\033[0m")


def safe(text):
    return monitor.CONTROL.sub("", str(text or ""))


def git_state(cwd):
    """(root, "⑂ main ↑1 ~2") or (None, None) outside a work tree."""
    out = subprocess.run(["git", "--no-optional-locks", "-C", cwd, "status", "--porcelain=v2", "--branch"],
                         capture_output=True, text=True, timeout=2)
    if out.returncode != 0:
        return None, None
    branch, counts = "?", {"↑": 0, "↓": 0, "+": 0, "~": 0, "?": 0}
    for line in out.stdout.splitlines():
        if line.startswith("# branch.head "):
            branch = line.split(" ", 2)[2]
        elif line.startswith("# branch.ab "):
            ahead, behind = line.split()[2:4]
            counts["↑"], counts["↓"] = int(ahead[1:]), int(behind[1:])
        elif line[:2] in ("1 ", "2 ", "u "):
            xy = line.split()[1]
            counts["+"] += xy[0] != "."
            counts["~"] += xy[1] != "."
        elif line.startswith("? "):
            counts["?"] += 1
    root = subprocess.run(["git", "--no-optional-locks", "-C", cwd, "rev-parse", "--show-toplevel"],
                          capture_output=True, text=True, timeout=2).stdout.strip()
    marks = " ".join(f"{k}{v}" for k, v in counts.items() if v)
    return root or None, f"⑂ {safe(branch)}" + (f" {marks}" if marks else " ✓")


def lines(cwd, provider, session):
    model, account = monitor.agent_info({"agent": provider, "agent_session": {"value": session}, "cwd": cwd})
    color = ACCOUNT.get(account or "", "38;2;147;153;178")
    out = [f"\033[1;{color}m● {safe(account or provider)}{RESET}  {MAUVE}{safe(model or '')}{RESET}"]
    out.append(f"{BLUE}{safe(cwd.replace(HOME, '~', 1))}{RESET}")
    root, state = git_state(cwd)
    if state:
        out.append(f"{YELLOW if '✓' not in state else GREEN}{state}{RESET}")
    if root:
        boxes = services.containers(root, services.saved_snapshot("docker"))
        procs = services.listeners(root, services.saved_snapshot("ss"))
        items = [(b["name"], (b["urls"] or [""])[0], b["state"] == "running") for b in boxes]
        items += [(p["name"], p["url"], True) for p in procs]
        for name, url, up in items[:MAX_SERVICES]:
            out.append(f"{GREEN if up else DIM}●{RESET} {safe(name)} {SKY}{safe(url)}{RESET}")
        if len(items) > MAX_SERVICES:
            out.append(f"{DIM}+{len(items) - MAX_SERVICES} services (prefix+ctrl+g){RESET}")
    return out


def main():
    cwd, provider, session = (sys.argv[1:4] + ["", "", ""])[:3]
    if not os.path.isdir(cwd):
        return
    print("\n".join(lines(cwd, provider, session)))


if __name__ == "__main__":
    main()
