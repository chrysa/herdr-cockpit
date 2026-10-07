"""Reconcile installed herdr plugins with cockpit/plugins.toml.

`diff` is pure: given the manifest and `herdr plugin list --json`, it returns
the actions setup must run (install, enable, disable) and the drift status must
report (pinned commit differs, plugin installed but not in the manifest).
Nothing is ever uninstalled: extra plugins are only reported.
"""
import json
import os
import subprocess
import tomllib

MANIFEST = os.path.join(os.path.dirname(os.path.abspath(__file__)), "plugins.toml")


def load_manifest(path=MANIFEST):
    with open(path, "rb") as fh:
        return tomllib.load(fh).get("plugin", [])


def installed(run=subprocess.run):
    out = run(["herdr", "plugin", "list", "--json"], capture_output=True, text=True, check=False)
    data = json.loads(out.stdout or "{}")
    data = data.get("result", data)
    return data.get("plugins", data) if isinstance(data, dict) else data


def diff(manifest, listing):
    """(actions, drift): actions are argv lists for `herdr`, drift is human-readable lines."""
    have = {p["plugin_id"]: p for p in listing}
    actions, drift = [], []
    for want in manifest:
        pid, enabled = want["id"], want.get("enabled", True)
        current = have.get(pid)
        if current is None:
            install = ["plugin", "install", want["source"], "--yes"]
            if want.get("ref"):
                install[3:3] = ["--ref", want["ref"]]
            actions.append(install)
            if not enabled:
                actions.append(["plugin", "disable", pid])
            continue
        if bool(current.get("enabled", True)) != bool(enabled):
            actions.append(["plugin", "enable" if enabled else "disable", pid])
        source = current.get("source") or {}
        pinned, actual = want.get("ref"), source.get("resolved_commit")
        if pinned and source.get("kind") == "github" and actual and actual != pinned:
            drift.append(f"{pid}: installed {actual[:8]}, manifest pins {pinned[:8]}")
    known = {w["id"] for w in manifest}
    drift += [f"{pid}: installed but not in plugins.toml" for pid in sorted(have) if pid not in known]
    return actions, drift
