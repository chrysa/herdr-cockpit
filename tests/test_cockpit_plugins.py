import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "cockpit"))

import plugins  # noqa: E402


def test_missing_plugin_is_installed_at_its_pinned_ref_then_disabled():
    manifest = [{"id": "x", "source": "o/x", "ref": "abc", "enabled": False}]
    actions, drift = plugins.diff(manifest, [])
    assert actions == [["plugin", "install", "o/x", "--ref", "abc", "--yes"], ["plugin", "disable", "x"]]
    assert drift == []


def test_enabled_state_is_applied_and_extras_only_reported():
    manifest = [{"id": "x", "source": "o/x", "enabled": True}]
    listing = [{"plugin_id": "x", "enabled": False}, {"plugin_id": "y", "enabled": True}]
    actions, drift = plugins.diff(manifest, listing)
    assert actions == [["plugin", "enable", "x"]]
    assert drift == ["y: installed but not in plugins.toml"]


def test_shipped_manifest_is_well_formed():
    manifest = plugins.load_manifest()
    ids = [p["id"] for p in manifest]
    assert len(ids) == len(set(ids))
    assert all(p["source"] for p in manifest)
    assert "chrysa.cockpit" in ids
