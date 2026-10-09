import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "cockpit"))

import setup  # noqa: E402


class FakeRun:
    """Stands in for subprocess.run: systemd units inactive, plugins disabled."""

    def __init__(self):
        self.calls = []
        self.active = set()
        self.enabled = set()

    def __call__(self, args, **kwargs):
        self.calls.append(args)
        out = ""
        if args[:3] == ["systemctl", "--user", "is-active"]:
            out = "active" if args[3] in self.active else "inactive"
        elif args[:3] == ["systemctl", "--user", "enable"]:
            self.active.add(args[-1])
        elif args[:3] == ["herdr", "plugin", "list"]:
            out = json.dumps({"result": {"plugins": [
                {"plugin_id": w["id"], "enabled": w["id"] in self.enabled,
                 "source": {"kind": "github", "resolved_commit": w.get("ref")}}
                for w in setup.plugins.load_manifest()]}})
        elif args[:3] == ["herdr", "plugin", "enable"]:
            self.enabled.add(args[3])
        elif args[:3] == ["herdr", "plugin", "disable"]:
            self.enabled.discard(args[3])
        return subprocess.CompletedProcess(args, 0, stdout=out, stderr="")


def make_home(tmp_path):
    for account in (".claude-perso", ".claude-pro"):
        (tmp_path / account).mkdir()
        (tmp_path / account / "settings.json").write_text(json.dumps(
            {"statusLine": {"command": "/old.sh", "refreshInterval": 10}, "keep": True}))
    herdr = tmp_path / ".config" / "herdr"
    herdr.mkdir(parents=True)
    (herdr / "config.toml").write_text("old config\n")
    return setup.Paths(home=str(tmp_path))


def test_first_run_installs_everything(tmp_path):
    paths = make_home(tmp_path)
    changes = setup.Setup(paths, run=FakeRun()).apply()
    assert changes
    assert os.readlink(paths.herdr_config) == os.path.join(paths.rendered, "config.toml")
    for account in (".claude-perso", ".claude-pro"):
        settings = json.loads((tmp_path / account / "settings.json").read_text())
        assert settings["statusLine"]["command"] == os.path.join(paths.rendered, "statusline.sh")
        assert settings["keep"] is True
    unit = (tmp_path / ".config/systemd/user/herdr-config-reload.path").read_text()
    assert os.path.join(paths.rendered, "config.toml") in unit
    assert "{{" not in unit


def test_second_run_is_a_no_op(tmp_path):
    paths = make_home(tmp_path)
    run = FakeRun()
    setup.Setup(paths, run=run).apply()
    assert setup.Setup(paths, run=run).apply() == []


def test_replaced_files_are_backed_up(tmp_path):
    paths = make_home(tmp_path)
    setup.Setup(paths, run=FakeRun()).apply()
    backups = os.listdir(os.path.join(paths.state, "backups"))
    assert len(backups) == 1
    saved = os.listdir(os.path.join(paths.state, "backups", backups[0]))
    assert any(name.endswith("herdr__config.toml") for name in saved)


def test_dry_run_touches_nothing(tmp_path):
    paths = make_home(tmp_path)
    run = FakeRun()
    changes = setup.Setup(paths, dry_run=True, run=run).apply()
    assert changes
    assert not os.path.islink(paths.herdr_config)
    assert not os.path.exists(paths.state)
    assert not any(call[:3] in (["herdr", "plugin", "enable"], ["herdr", "plugin", "disable"],
                                ["herdr", "plugin", "install"]) for call in run.calls)


def test_auto_title_settings_are_linked(tmp_path):
    paths = make_home(tmp_path)
    setup.Setup(paths, run=FakeRun()).apply()
    link = tmp_path / ".config" / "herdr-auto-title" / "config.env"
    assert os.readlink(link) == os.path.join(paths.rendered, "auto-title.env")
    assert "HERDR_AUTO_TITLE_MAX_LENGTH" in link.read_text()
