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
    assert len(name) <= 32
    assert name[0].isalpha()


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


def a(pane, status, name=None, ws="w1"):
    return {"pane_id": pane, "agent_status": status, "name": name, "workspace_id": ws}


def test_blocked_transitions_only_on_change():
    previous = {}
    assert monitor.blocked_transitions([a("p1", "blocked")], previous) == []
    assert monitor.blocked_transitions([a("p1", "blocked")], previous) == []
    assert monitor.blocked_transitions([a("p1", "working")], previous) == []
    fresh = monitor.blocked_transitions([a("p1", "blocked")], previous)
    assert [x["pane_id"] for x in fresh] == ["p1"]


def test_blocked_transitions_forget_closed_panes():
    previous = {}
    monitor.blocked_transitions([a("p1", "idle"), a("p2", "idle")], previous)
    monitor.blocked_transitions([a("p1", "idle")], previous)
    assert set(previous) == {"p1"}


def test_notify_blocked_falls_back_to_herdr_toast():
    calls = []

    def run(args, **kwargs):
        calls.append(args)
        if args[0] == "notify-send":
            raise FileNotFoundError
        return subprocess.CompletedProcess(args, 0)

    monitor.notify_blocked(a("p1", "blocked", name="padam-av-x\x1b[2J"), {"w1": "padam-av"}, run=run)
    assert calls[0][0] == "notify-send"
    assert calls[1][1:3] == ["notification", "show"]
    assert "\x1b" not in calls[1][3]
    assert calls[1][3] == "‼ padam-av-x[2J attend une réponse"


def test_restored_auto_names_are_still_ours():
    assert monitor.is_auto_name("padam-av-pdf-complet", "padam-av")
    assert monitor.is_auto_name("padam-av-pdf-complet-2", "padam-av")
    assert not monitor.is_auto_name("mon-agent", "padam-av")
    assert not monitor.is_auto_name("padam-avx", "padam-av")


def test_auto_rename_updates_restored_name_but_keeps_manual(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(monitor, "STATE_DIR", str(tmp_path))
    monkeypatch.setattr(monitor, "NAMED_FILE", str(tmp_path / "named.json"))
    monkeypatch.setattr(monitor, "herdr", lambda *args: calls.append(args) or {})
    agents = [
        {"pane_id": "p1", "name": "padam-av-pdf-complet", "workspace_id": "w1",
         "terminal_title_stripped": "Scheduler dynamique", "cwd": "/x"},
        {"pane_id": "p2", "name": "mon-agent", "workspace_id": "w1",
         "terminal_title_stripped": "Autre sujet", "cwd": "/x"},
    ]
    named = {}
    monitor.auto_rename(agents, named, [{"workspace_id": "w1", "label": "padam-av"}])
    assert ("agent", "rename", "p1", "padam-av-scheduler-dynamique") in calls
    assert not any(call[2] == "p2" for call in calls if call[:2] == ("agent", "rename"))
    assert named == {"p1": "padam-av-scheduler-dynamique"}
