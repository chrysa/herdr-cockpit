import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "cockpit"))

import render  # noqa: E402
import status  # noqa: E402


def test_config_ok_when_identical(tmp_path):
    installed = tmp_path / "config.toml"
    installed.write_text(render.render_file("config.toml"))
    assert status.check_config(str(installed))[0] == "ok"


def test_config_drift_shows_diff(tmp_path):
    installed = tmp_path / "config.toml"
    installed.write_text(render.render_file("config.toml").replace("prefix = ", "prefix  = ", 1))
    state, detail = status.check_config(str(installed))
    assert state == "drift"
    assert "prefix" in detail


def test_config_missing(tmp_path):
    assert status.check_config(str(tmp_path / "nope.toml"))[0] == "missing"


def write_account(tmp_path, name, command):
    d = tmp_path / name
    d.mkdir()
    settings = {"statusLine": {"command": command}} if command else {}
    (d / "settings.json").write_text(json.dumps(settings))
    return str(d)


def test_statusline_ok_when_all_accounts_agree(tmp_path):
    dirs = [write_account(tmp_path, n, "/s.sh") for n in (".claude-perso", ".claude-pro")]
    assert status.check_statusline(dirs)[0] == "ok"


def test_statusline_drift_when_accounts_differ(tmp_path):
    dirs = [write_account(tmp_path, ".claude-perso", "/s.sh"), write_account(tmp_path, ".claude-pro", "/old.sh")]
    assert status.check_statusline(dirs)[0] == "drift"


def test_statusline_missing_on_one_account(tmp_path):
    dirs = [write_account(tmp_path, ".claude-perso", "/s.sh"), write_account(tmp_path, ".claude-pro", None)]
    state, detail = status.check_statusline(dirs)
    assert state == "missing"
    assert ".claude-pro" in detail


def test_plugins_states():
    ok = [{"plugin_id": p, "enabled": True} for p in status.REQUIRED_PLUGINS]
    assert status.check_plugins(ok)[0] == "ok"
    assert status.check_plugins(ok[:1])[0] == "missing"
    disabled = [dict(ok[0]), {"plugin_id": ok[1]["plugin_id"], "enabled": False}]
    assert status.check_plugins(disabled)[0] == "drift"


def test_units_states():
    assert status.check_units(lambda unit: True)[0] == "ok"
    state, detail = status.check_units(lambda unit: unit.endswith(".timer"))
    assert state == "missing"
    assert "herdr-config-reload.path" in detail
