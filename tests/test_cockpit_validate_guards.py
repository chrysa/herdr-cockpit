import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "cockpit"))

import render  # noqa: E402
import setup  # noqa: E402
import validate  # noqa: E402


def test_shipped_palette_and_templates_are_valid():
    palette = render.load_palette()
    palette["paths"] = {"config": "/c", "bin": "/b"}
    assert validate.check_palette(palette) == []
    errors, rendered = validate.check_templates(palette)
    assert errors == []
    assert "config.toml" in rendered


def test_palette_errors_are_reported():
    palette = render.load_palette()
    palette["colors"]["blue"] = "blue"
    palette["colors"]["slots"] = palette["colors"]["slots"][:3]
    errors = validate.check_palette(palette)
    assert any("not #RRGGBB" in e for e in errors)
    assert any("expected 8" in e for e in errors)


def test_herdr_check_skipped_without_herdr(monkeypatch):
    monkeypatch.setattr(validate.shutil, "which", lambda name: None)
    errors, note = validate.check_herdr("x = 1\n")
    assert errors == []
    assert "skipped" in note


def git(path, *args):
    subprocess.run(["git", "-C", str(path), *args], check=True, capture_output=True)


def test_source_drift(tmp_path):
    git(tmp_path, "init", "-q", "-b", "main")
    git(tmp_path, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", "a")
    git(tmp_path, "update-ref", "refs/remotes/origin/main", "HEAD")
    assert setup.source_drift(str(tmp_path)) is None
    (tmp_path / "x").write_text("dirty")
    assert "uncommitted" in setup.source_drift(str(tmp_path))
    git(tmp_path, "add", "x")
    git(tmp_path, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "b")
    assert "origin/main" in setup.source_drift(str(tmp_path))


def test_source_drift_outside_git(tmp_path):
    assert setup.source_drift(str(tmp_path)) is None
