import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "cockpit"))

import render  # noqa: E402


def test_config_renders_byte_for_byte():
    with open(os.path.join(ROOT, "tests", "fixtures", "config.toml")) as fh:
        expected = fh.read()
    assert render.render_file("config.toml") == expected


def test_template_has_no_hardcoded_palette_color():
    palette = render.load_palette()
    with open(os.path.join(ROOT, "cockpit", "templates", "config.toml")) as fh:
        template = fh.read()
    for value in palette["colors"].values():
        if isinstance(value, str):
            assert value not in template


def test_unknown_placeholder_fails():
    palette = render.load_palette()
    with pytest.raises(KeyError):
        render.render("{{colors.nope}}", palette)


@pytest.mark.parametrize("name", ["../palette.toml", "/etc/passwd", "missing.toml"])
def test_render_file_rejects_unknown_templates(name):
    with pytest.raises(ValueError):
        render.render_file(name)


def test_palette_slots_reference_known_colors():
    palette = render.load_palette()
    assert len(palette["colors"]["slots"]) == 8
    assert all(name in palette["colors"] for name in palette["colors"]["slots"])
