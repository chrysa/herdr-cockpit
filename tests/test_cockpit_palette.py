import json
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "cockpit"))

import render  # noqa: E402
import setup  # noqa: E402
sys.path.insert(0, os.path.join(ROOT, "tests"))
from test_cockpit_setup import FakeRun, make_home  # noqa: E402


def test_rgb():
    assert render.rgb("#89b4fa") == "137;180;250"


@pytest.mark.parametrize("name", render.templates())
def test_every_template_renders_completely(name):
    palette = render.load_palette()
    palette["paths"] = {"config": "/c", "bin": "/b"}
    assert "{{" not in render.render_file(name, palette)


def test_palette_json_is_valid_and_complete():
    data = json.loads(render.render_file("palette.json"))
    assert set(data["accounts"]) == {"perso", "pro", "codex", "other"}
    assert data["symbols"]["blocked"] == "‼"


def test_opencode_theme_references_only_defined_colors():
    theme = json.loads(render.render_file("opencode-theme.json"))
    assert set(theme["theme"].values()) <= set(theme["defs"])


def test_setup_installs_and_selects_opencode_theme(tmp_path):
    paths = make_home(tmp_path)
    opencode = tmp_path / ".config" / "opencode"
    opencode.mkdir(parents=True)
    (opencode / "tui.jsonc").write_text(json.dumps({"plugin": ["./x.js"]}))
    setup.Setup(paths, run=FakeRun()).apply()
    theme = opencode / "themes" / "chrysa-cockpit.json"
    assert os.readlink(theme) == os.path.join(paths.rendered, "opencode-theme.json")
    tui = json.loads((opencode / "tui.jsonc").read_text())
    assert tui == {"plugin": ["./x.js"], "theme": "chrysa-cockpit"}


def test_setup_leaves_commented_tui_config_alone(tmp_path):
    paths = make_home(tmp_path)
    opencode = tmp_path / ".config" / "opencode"
    opencode.mkdir(parents=True)
    original = '{\n  // mine\n  "plugin": []\n}\n'
    (opencode / "tui.jsonc").write_text(original)
    setup.Setup(paths, run=FakeRun()).apply()
    assert (opencode / "tui.jsonc").read_text() == original
