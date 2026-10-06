import subprocess

import pytest

import monitor


@pytest.mark.parametrize("raw, short", [
    ("claude-opus-5-5", "opus-5.5"),
    ("claude-sonnet-4-5-20250929", "sonnet-4.5"),
    ("gpt-6.1-sol", "gpt-6.1-sol"),
])
def test_short_model(raw, short):
    assert monitor.short_model(raw) == short


@pytest.mark.parametrize("text, expected", [
    ("Herdr amélioration", "herdr-amelioration"),
    ("  PDF plus complet!! ", "pdf-plus-complet"),
    ("", ""),
])
def test_slug(text, expected):
    assert monitor.slug(text) == expected


def agent(title, cwd="/x/repo"):
    return {"terminal_title_stripped": title, "cwd": cwd}


def test_theme_name_uses_space_and_topic():
    assert monitor.theme_name(agent("Scheduler dynamique Django"), "padam-av") == "padam-av-scheduler-dynamique"


def test_theme_name_shortens_long_space():
    assert monitor.theme_name(agent("Récapitulatif PRs"), "Forge-Stack-Workshop") == "forge-recapitulatif-prs"


def test_theme_name_falls_back_to_folder_on_generic_title():
    name = monitor.theme_name(agent("Claude Code", "/p/padam-av-simul"), "padam-av-simul")
    assert name == "padam-av-simul"


def test_theme_name_is_valid_herdr_name():
    name = monitor.theme_name(agent("123 ### tâche très très longue avec beaucoup de mots"), "9lives")
    assert len(name) <= 32 and name[0].isalpha()


@pytest.mark.parametrize("tokens, billed", [
    ({"context": "5h 86% · 18%"}, False),
    ({"context": "5h 0% · 18%"}, True),
    ({"limit": "Σ 425k $0.04"}, True),
    ({}, False),
])
def test_is_billed(tokens, billed):
    assert monitor.is_billed(tokens) is billed


def git(cwd, *args):
    subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True)


def test_git_summary_clean_and_dirty(tmp_path):
    git(tmp_path, "init", "-q", "-b", "main")
    git(tmp_path, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", "init")
    assert monitor.git_summary(str(tmp_path)) == "⑂ main ✓"
    (tmp_path / "new.txt").write_text("x")
    assert monitor.git_summary(str(tmp_path)) == "⑂ main ?1"


def test_git_summary_outside_repo(tmp_path):
    assert monitor.git_summary(str(tmp_path)) is None
