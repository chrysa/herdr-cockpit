#!/usr/bin/env python3
"""Read-only drift report for the cockpit setup.

One line per item: ok, drift (with a short diff) or missing. Never writes.
Exit code 0 when everything is ok, 1 otherwise, so it can gate scripts.
"""
import difflib
import glob
import json
import os
import shutil
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import plugins  # noqa: E402
import render  # noqa: E402

HOME = os.path.expanduser("~")
SYSTEMD_UNITS = ("herdr-config-reload.path", "herdr-logrotate.timer")


def setup_palette():
    """The palette setup renders with, paths included, so status compares like for like."""
    import setup  # local import: setup imports this module's neighbours, not status
    return setup.Setup(setup.Paths(), dry_run=True).palette()


def check_config(installed=os.path.join(HOME, ".config", "herdr", "config.toml")):
    """Installed herdr config vs the rendered template."""
    if not os.path.exists(installed):
        return "missing", installed
    with open(installed) as fh:
        current = fh.read()
    expected = render.render_file("config.toml", setup_palette())
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


def check_plugins(listing=None, manifest=None):
    """Installed plugins vs plugins.toml: missing, wrong enabled state, version drift, extras."""
    manifest = plugins.load_manifest() if manifest is None else manifest
    listing = plugins.installed() if listing is None else listing
    actions, drift = plugins.diff(manifest, listing)
    if actions:
        return "missing", "; ".join("herdr " + " ".join(a) for a in actions)
    if drift:
        return "drift", "\n".join(drift)
    return "ok", f"{len(manifest)} plugins as declared"


def check_units(is_active=None):
    """systemd user units that keep the setup live."""
    def default(unit):
        return subprocess.run(["systemctl", "--user", "is-active", unit],
                              capture_output=True, text=True).stdout.strip() == "active"
    inactive = [u for u in SYSTEMD_UNITS if not (is_active or default)(u)]
    return ("missing", ", ".join(inactive)) if inactive else ("ok", ", ".join(SYSTEMD_UNITS))


MIN_HERDR = (0, 9, 0)
TOOLS = ("git", "docker", "ss", "jq", "notify-send")


def check_daemon(pidfile=os.path.join(HOME, ".local", "state", "chrysa.cockpit", "daemon.pid")):
    """The shared cockpit daemon (sidebar tokens, auto-naming, notifications) is running."""
    try:
        with open(pidfile) as fh:
            pid = int(fh.read().strip())
        os.kill(pid, 0)
    except (OSError, ValueError):
        return "missing", "cockpit daemon not running (python3 cockpit/daemon.py ensure)"
    return "ok", f"cockpit daemon pid {pid}"


def parse_version(text):
    """"herdr 0.9.1" -> (0, 9, 1); None when unreadable."""
    for word in text.split():
        parts = word.lstrip("v").split(".")
        if len(parts) >= 2 and all(p.isdigit() for p in parts[:3]):
            return tuple(int(p) for p in parts[:3])
    return None


def check_herdr_version(run=subprocess.run):
    try:
        out = run(["herdr", "--version"], capture_output=True, text=True, timeout=10).stdout
    except (OSError, subprocess.SubprocessError):
        return "missing", "herdr not found"
    version = parse_version(out)
    if version is None:
        return "drift", f"unreadable herdr version: {out.strip()!r}"
    wanted = ".".join(map(str, MIN_HERDR))
    if version < MIN_HERDR:
        return "drift", f"herdr {'.'.join(map(str, version))} < {wanted}"
    return "ok", f"herdr {'.'.join(map(str, version))} (>= {wanted})"


def check_tools(which=shutil.which):
    """External tools the panel and status line rely on."""
    missing = [tool for tool in TOOLS if not which(tool)]
    if missing:
        return "drift", "missing: " + ", ".join(missing) + " (related panel sections stay empty)"
    return "ok", ", ".join(TOOLS)


CHECKS = {"config": check_config, "statusline": check_statusline,
          "plugins": check_plugins, "units": check_units,
          "daemon": check_daemon, "herdr": check_herdr_version, "tools": check_tools}


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
