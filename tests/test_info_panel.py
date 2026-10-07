import info


def test_group_by_state_keeps_order_and_maps_unknown_to_idle():
    agents = [{"agent_status": s} for s in ("idle", "working", "blocked", "unknown", "done")]
    groups = info.group_by_state(agents)
    assert list(groups) == ["blocked", "working", "done", "idle"]
    assert len(groups["idle"]) == 2


def test_header_fills_width():
    plain = info.ANSI.sub("", info.header("Tâches", 30, "2/5"))
    assert plain.startswith("── Tâches ")
    assert plain.endswith(" 2/5")
    assert len(plain) == 29


def test_safe_strips_escape_sequences():
    assert info.safe("ok\x1b]0;pwn\x07\x1b[2J") == "ok]0;pwn"


import subprocess  # noqa: E402

import pytest  # noqa: E402


@pytest.mark.parametrize("segment, color", [
    ("▓▓░░░░░░ 80k", "ok"),
    ("▓▓▓▓▓░░░ 200k", "yel"),
    ("▓▓▓▓▓▓▓░ 350k", "warn"),
    ("◔ 5h·20% · 7d·85%", "ok"),
    ("♻ 99% cached", "ok"),
    ("✂ 10%", "warn"),
])
def test_color_usage(segment, color):
    assert info.color_usage(segment).startswith(info.C[color])


def test_git_details(tmp_path, monkeypatch):
    monkeypatch.setattr(info, "ALLOWED_ROOTS", (str(tmp_path),))
    def git(*args):
        subprocess.run(["git", "-C", str(tmp_path), *args], check=True, capture_output=True)
    git("init", "-q", "-b", "main")
    (tmp_path / "a.txt").write_text("one\n")
    git("add", "a.txt")
    git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "init")
    (tmp_path / "a.txt").write_text("one\ntwo\n")
    (tmp_path / "b.txt").write_text("x")
    branch, counts, shortstat = info.git_details(str(tmp_path))
    assert branch == "main"
    assert counts["changed"] == 1
    assert counts["untracked"] == 1
    assert shortstat == "+1 -0 (1 fichier)"


def test_git_details_outside_repo(tmp_path):
    assert info.git_details(str(tmp_path)) is None


def test_each_quota_window_has_its_own_color():
    rendered = info.color_usage("◔ 5h·20% · 7d·85%")
    assert info.C["ok"] + "◔ 5h·20%" in rendered
    assert info.C["warn"] + "7d·85%" in rendered


def test_parse_shortstat():
    assert info.parse_shortstat(" 4 files changed, 12 insertions(+), 3 deletions(-)") == (4, 12, 3)
    assert info.parse_shortstat(" 1 file changed, 2 deletions(-)") == (1, 0, 2)
    assert info.parse_shortstat("") == (0, 0, 0)


def test_path_lines_show_current_dir_and_repo(tmp_path, monkeypatch):
    monkeypatch.setattr(info, "ALLOWED_ROOTS", (str(tmp_path),))
    subprocess.run(["git", "-C", str(tmp_path), "init", "-q"], check=True)
    (tmp_path / "src").mkdir()
    plain = [info.ANSI.sub("", line) for line in info.path_lines(info.cutter(200), 200, str(tmp_path / "src"))]
    assert plain[0] == str(tmp_path / "src")
    assert plain[1].strip() == f"dépôt {tmp_path.name}"


def test_path_lines_outside_repo_show_full_cwd(tmp_path):
    plain = [info.ANSI.sub("", line) for line in info.path_lines(info.cutter(200), 200, str(tmp_path))]
    assert plain == [str(tmp_path)]


import sqlite3  # noqa: E402


def make_rtk_db(path, rows):
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE commands (project_path TEXT, timestamp TEXT, input_tokens INT, saved_tokens INT)")
    conn.executemany("INSERT INTO commands VALUES (?, ?, ?, ?)", rows)
    conn.commit()
    conn.close()


def test_rtk_stats_counts_project_subtree_only(tmp_path):
    db = str(tmp_path / "history.db")
    make_rtk_db(db, [
        ("/p/app", "2026-10-06T10:00:00+00:00", 100, 40),
        ("/p/app/sub", "2026-10-06T11:00:00+00:00", 100, 60),
        ("/p/application", "2026-10-06T11:00:00+00:00", 999, 999),
    ])
    assert info.rtk_stats("/p/app", db=db) == (2, 200, 100)
    assert info.rtk_stats("/p/app", "2026-10-06T10:30:00+00:00", db=db) == (1, 100, 60)


def test_rtk_stats_without_database(tmp_path):
    assert info.rtk_stats("/p/app", db=str(tmp_path / "missing.db")) is None


def test_human():
    assert info.human(1_234) == "1.2K"
    assert info.human(3_400_000) == "3.4M"
    assert info.human(12) == "12"


def test_wrap_path_keeps_every_character():
    path = "/home/anthony/Documents/perso/projects/chrysa/herdr-cockpit"
    parts = info.wrap_path(path, 22)
    assert "".join(parts) == path
    assert all(len(p) <= 20 for p in parts)
    assert parts[0].endswith("/")


def test_conversation_dir_prefers_status_line(tmp_path, monkeypatch):
    monkeypatch.setattr(info, "ALLOWED_ROOTS", (str(tmp_path),))
    real, pane = tmp_path / "real", tmp_path / "pane"
    real.mkdir()
    pane.mkdir()
    agent = {"cwd": str(pane), "foreground_cwd": str(pane)}
    assert info.conversation_dir(agent, {"dir": str(real)}) == str(real)
    assert info.conversation_dir(agent, {"dir": "/does/not/exist"}) == str(pane)
    assert info.conversation_dir(agent, {}) == str(pane)


def test_safe_dir_rejects_option_like_and_relative_paths(tmp_path, monkeypatch):
    monkeypatch.setattr(info, "ALLOWED_ROOTS", (str(tmp_path),))
    assert info.safe_dir(str(tmp_path)) == str(tmp_path)
    assert info.safe_dir("/etc") == ""
    assert info.safe_dir("--output=/etc/passwd") == ""
    assert info.safe_dir("relative/dir") == ""
    assert info.safe_dir(str(tmp_path) + "\x1b[2J") == ""
    assert info.safe_dir("/does/not/exist") == ""
    assert info.safe_dir(None) == ""


def test_git_helpers_refuse_unsafe_paths():
    assert info.git_details("-c core.pager=evil") is None
    assert info.project_root("--help") is None


def test_worktrees_lists_every_tree_and_marks_the_current_one(tmp_path, monkeypatch):
    monkeypatch.setattr(info, "ALLOWED_ROOTS", (str(tmp_path),))
    main = tmp_path / "main"
    main.mkdir()

    def git(*args):
        subprocess.run(["git", "-C", str(main), *args], check=True, capture_output=True)
    git("init", "-q", "-b", "main")
    git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", "init")
    git("worktree", "add", "-q", "-b", "feat", str(tmp_path / "feat"))
    trees = info.worktrees(str(tmp_path / "feat"))
    assert [(b, cur) for _, b, cur in trees] == [("main", False), ("feat", True)]


def test_agents_by_worktree(tmp_path, monkeypatch):
    monkeypatch.setattr(info, "ALLOWED_ROOTS", (str(tmp_path),))
    main, feat = tmp_path / "app", tmp_path / "app-feat"
    (main / "src").mkdir(parents=True)
    feat.mkdir()
    trees = [(str(main), "main", True), (str(feat), "feat", False)]
    agents = [{"name": "padam-av-x", "cwd": str(main / "src"), "workspace_id": "w1"},
              {"name": "other", "cwd": str(feat), "workspace_id": "w2"}]
    busy = info.agents_by_worktree(trees, agents, {"w1": "padam-av", "w2": "chrysa"})
    assert busy == {str(main): ["padam-av-x"], str(feat): ["other (chrysa)"]}


def test_is_scratch():
    assert info.is_scratch(info.tempfile.gettempdir() + "/claude-1000/x")
    assert not info.is_scratch("/home/u/projects/app")


def test_services_need_a_git_project(tmp_path, monkeypatch):
    monkeypatch.setattr(info, "ALLOWED_ROOTS", (str(tmp_path),))
    called = []
    monkeypatch.setattr(info.services, "services", lambda root: called.append(root) or ([], []))
    assert info.section_services(info.cutter(40), 40, str(tmp_path)) == []
    assert called == []




@pytest.mark.parametrize("remote, url", [
    ("git@github.com:chrysa/herdr-cockpit.git", "https://github.com/chrysa/herdr-cockpit"),
    ("https://github.com/chrysa/dotfiles.git", "https://github.com/chrysa/dotfiles"),
    ("https://user:secret@github.com/o/r.git", "https://github.com/o/r"),
    ("ssh://git@gitlab.com:2222/team/app.git", "https://gitlab.com/team/app"),
])
def test_browsable(remote, url):
    assert info.browsable(remote) == url


def test_finished_subagents_are_hidden(monkeypatch):
    monkeypatch.setattr(info, "subagents_for", lambda s: [(False, "explore", "done"), (True, "security-auditor", "x")])
    plain = [info.ANSI.sub("", line) for line in info.section_subagents(info.cutter(60), 60, "s")]
    assert any("security-auditor" in line for line in plain)
    assert not any("explore" in line for line in plain)


def test_no_subagent_section_when_all_finished(monkeypatch):
    monkeypatch.setattr(info, "subagents_for", lambda s: [(False, "explore", "done")])
    assert info.section_subagents(info.cutter(60), 60, "s") == []


def test_projects_of_groups_agents_by_git_root(tmp_path, monkeypatch):
    monkeypatch.setattr(info, "ALLOWED_ROOTS", (str(tmp_path),))
    app, other = tmp_path / "app", tmp_path / "notes"
    (app / "src").mkdir(parents=True)
    other.mkdir()
    subprocess.run(["git", "-C", str(app), "init", "-q"], check=True)
    agents = [{"pane_id": "1", "cwd": str(app / "src")}, {"pane_id": "2", "cwd": str(app)},
              {"pane_id": "3", "cwd": str(other)}, {"pane_id": "4", "cwd": "/etc"}]
    projects = info.projects_of(agents)
    assert {k: [a["pane_id"] for a in v] for k, v in projects.items()} == {
        str(app): ["1", "2"], str(other): ["3"]}


def test_prunable_worktrees_are_counted_and_pruned(tmp_path, monkeypatch):
    monkeypatch.setattr(info, "ALLOWED_ROOTS", (str(tmp_path),))
    main = tmp_path / "main"
    main.mkdir()

    def git(*args):
        subprocess.run(["git", "-C", str(main), *args], check=True, capture_output=True)
    git("init", "-q", "-b", "main")
    git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", "init")
    git("worktree", "add", "-q", "-b", "gone", str(tmp_path / "gone"))
    import shutil as sh
    sh.rmtree(tmp_path / "gone")
    info.project_root.cache.clear()
    trees = info.worktrees(str(main))
    assert [b for _, b, _ in trees] == ["main"]
    assert info.PRUNABLE[str(main.resolve())] == 1
    assert info.prune_worktrees(str(main))
    info.worktrees(str(main))
    assert info.PRUNABLE[str(main.resolve())] == 0


def test_help_lists_every_key():
    plain = "\n".join(info.ANSI.sub("", line) for line in info.render_help(60)[0])
    for key in ("a", "e", "A", "t", "d", "s", "g", "u", "r", "w", "P", "?", "q"):
        assert f"  {key}" in plain
