"""Reconcile installed herdr plugins with cockpit/plugins.toml.

`diff` is pure: given the manifest and `herdr plugin list --json`, it returns
the actions setup must run (install, reinstall, enable, disable) and the drift
status must report (pinned source or commit differs, plugin not in the manifest).
A plugin whose source or pinned commit changed is reinstalled; plugins missing
from the manifest are only reported, never uninstalled.
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


def missing_actions(want):
    """Install at the pinned ref, then disable if the manifest says so."""
    install = ["plugin", "install", want["source"], "--yes"]
    if want.get("ref"):
        install[3:3] = ["--ref", want["ref"]]
    return [install] + ([] if want.get("enabled", True) else [["plugin", "disable", want["id"]]])


def compare(want, current):
    """(actions, drift) for a plugin that is installed."""
    actions, drift = [], []
    enabled = want.get("enabled", True)
    if bool(current.get("enabled", True)) != bool(enabled):
        actions.append(["plugin", "enable" if enabled else "disable", want["id"]])
    source = current.get("source") or {}
    if source.get("kind") == "github":
        repo, wanted_repo = f"{source.get('owner')}/{source.get('repo')}", want["source"]
        pinned, actual = want.get("ref"), source.get("resolved_commit")
        if source.get("owner") and repo.lower() != wanted_repo.lower():
            drift.append(f"{want['id']}: installed from {repo}, manifest wants {wanted_repo}")
        elif pinned and actual and actual != pinned:
            drift.append(f"{want['id']}: installed {actual[:8]}, manifest pins {pinned[:8]}")
        else:
            return actions, drift + disabled_drift(want, current)
        return [["plugin", "uninstall", want["id"]]] + missing_actions(want), drift
    return actions, drift + disabled_drift(want, current)


def disabled_drift(want, current):
    if not want.get("enabled", True) and not current.get("enabled", True):
        return [f"{want['id']}: installed but disabled — uninstall it and drop it from plugins.toml"]
    return []


def diff(manifest, listing):
    """(actions, drift): actions are argv lists for `herdr`, drift is human-readable lines."""
    have = {p["plugin_id"]: p for p in listing}
    actions, drift = [], []
    for want in manifest:
        current = have.get(want["id"])
        if current is None:
            actions += missing_actions(want)
            continue
        more_actions, more_drift = compare(want, current)
        actions += more_actions
        drift += more_drift
    known = {w["id"] for w in manifest}
    drift += [f"{pid}: installed but not in plugins.toml" for pid in sorted(have) if pid not in known]
    return actions, drift
