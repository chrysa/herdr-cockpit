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
    manifest = [{"id": "a", "source": "o/a", "ref": "1111", "enabled": True},
                {"id": "b", "source": "o/b", "enabled": False}]
    ok = [{"plugin_id": "a", "enabled": True, "source": {"kind": "github", "resolved_commit": "1111"}},
          {"plugin_id": "b", "enabled": False}]
    assert status.check_plugins(ok, manifest)[0] == "ok"
    assert status.check_plugins(ok[:1], manifest)[0] == "missing"
    stale = [dict(ok[0], source={"kind": "github", "resolved_commit": "2222"}), ok[1]]
    assert status.check_plugins(stale, manifest)[0] == "drift"
    extra = ok + [{"plugin_id": "c", "enabled": True}]
    assert "not in plugins.toml" in status.check_plugins(extra, manifest)[1]


def test_units_states():
    assert status.check_units(lambda unit: True)[0] == "ok"
    state, detail = status.check_units(lambda unit: unit.endswith(".timer"))
    assert state == "missing"
    assert "herdr-config-reload.path" in detail


def test_parse_version():
    assert status.parse_version("herdr 0.9.1") == (0, 9, 1)
    assert status.parse_version("v1.2") == (1, 2)
    assert status.parse_version("nope") is None


def test_daemon_check(tmp_path):
    pidfile = tmp_path / "daemon.pid"
    assert status.check_daemon(str(pidfile))[0] == "missing"
    pidfile.write_text(str(os.getpid()))
    assert status.check_daemon(str(pidfile))[0] == "ok"


def test_tools_check():
    assert status.check_tools(lambda tool: "/usr/bin/" + tool)[0] == "ok"
    state, detail = status.check_tools(lambda tool: None if tool == "docker" else "/x")
    assert state == "drift"
    assert "docker" in detail


def test_herdr_version_too_old():
    import subprocess as sp
    old = lambda *a, **k: sp.CompletedProcess(a, 0, stdout="herdr 0.8.4\n")
    assert status.check_herdr_version(old)[0] == "drift"
