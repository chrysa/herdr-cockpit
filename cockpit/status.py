#!/usr/bin/env python3
"""Read-only drift report for the cockpit setup.

One line per item: ok, drift (with a short diff) or missing. Never writes.
Exit code 0 when everything is ok, 1 otherwise, so it can gate scripts.
"""
import difflib
import glob
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import render  # noqa: E402

HOME = os.path.expanduser("~")
REQUIRED_PLUGINS = ("chrysa.spaces", "chrysa.agent-info")
SYSTEMD_UNITS = ("herdr-config-reload.path", "herdr-logrotate.timer")


def check_config(installed=os.path.join(HOME, ".config", "herdr", "config.toml")):
    """Installed herdr config vs the rendered template."""
    if not os.path.exists(installed):
        return "missing", installed
    with open(installed) as fh:
        current = fh.read()
    expected = render.render_file("config.toml")
    if current == expected:
        return "ok", installed
    diff = difflib.unified_diff(expected.splitlines(), current.splitlines(),
                                "rendered", "installed", n=0, lineterm="")
    return "drift", "\n".join(list(diff)[:20])


def check_statusline(claude_dirs=None):
    """Every Claude account points its status line at the same script."""
    dirs = claude_dirs or sorted({os.path.realpath(d) for d in glob.glob(f"{HOME}/.claude-*")
                                  if os.path.isfile(os.path.join(d, "settings.json"))})
    commands = {}
    for d in dirs:
        try:
            with open(os.path.join(d, "settings.json")) as fh:
                commands[os.path.basename(d)] = (json.load(fh).get("statusLine") or {}).get("command")
        except (OSError, ValueError):
            commands[os.path.basename(d)] = None
    if not commands:
        return "missing", "no Claude account found"
    if any(c is None for c in commands.values()):
        return "missing", ", ".join(k for k, c in commands.items() if c is None)
    if len(set(commands.values())) > 1:
        return "drift", "; ".join(f"{k}: {c}" for k, c in commands.items())
    return "ok", next(iter(commands.values()))


def check_plugins(listing=None):
    """Cockpit plugins installed and enabled."""
    if listing is None:
        out = subprocess.run(["herdr", "plugin", "list", "--json"], capture_output=True, text=True, timeout=10)
        data = json.loads(out.stdout or "{}")
        data = data.get("result", data)
        listing = data.get("plugins", data) if isinstance(data, dict) else data
    state = {p["plugin_id"]: p.get("enabled", False) for p in listing}
    missing = [p for p in REQUIRED_PLUGINS if p not in state]
    disabled = [p for p in REQUIRED_PLUGINS if state.get(p) is False]
    if missing:
        return "missing", ", ".join(missing)
    if disabled:
        return "drift", "disabled: " + ", ".join(disabled)
    return "ok", ", ".join(REQUIRED_PLUGINS)


def check_units(is_active=None):
    """systemd user units that keep the setup live."""
    def default(unit):
        return subprocess.run(["systemctl", "--user", "is-active", unit],
                              capture_output=True, text=True).stdout.strip() == "active"
    inactive = [u for u in SYSTEMD_UNITS if not (is_active or default)(u)]
    return ("missing", ", ".join(inactive)) if inactive else ("ok", ", ".join(SYSTEMD_UNITS))


CHECKS = {"config": check_config, "statusline": check_statusline,
          "plugins": check_plugins, "units": check_units}


def main():
    worst = 0
    for name, check in CHECKS.items():
        try:
            state, detail = check()
        except Exception as exc:  # report, never crash the whole report
            state, detail = "error", str(exc)
        worst = max(worst, state != "ok")
        print(f"{state:<8}{name:<12}{detail.splitlines()[0] if detail else ''}")
        for line in detail.splitlines()[1:]:
            print(f"{'':20}{line}")
    return worst


if __name__ == "__main__":
    sys.exit(main())
