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


def test_git_details(tmp_path):
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


def test_path_lines_show_root_and_subfolder(tmp_path):
    subprocess.run(["git", "-C", str(tmp_path), "init", "-q"], check=True)
    (tmp_path / "src").mkdir()
    plain = [info.ANSI.sub("", line) for line in info.path_lines(info.cutter(200), 200, str(tmp_path / "src"))]
    assert plain[0] == str(tmp_path)
    assert plain[1].strip() == "└ src"


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


def test_conversation_dir_prefers_status_line(tmp_path):
    real, pane = tmp_path / "real", tmp_path / "pane"
    real.mkdir()
    pane.mkdir()
    agent = {"cwd": str(pane), "foreground_cwd": str(pane)}
    assert info.conversation_dir(agent, {"dir": str(real)}) == str(real)
    assert info.conversation_dir(agent, {"dir": "/does/not/exist"}) == str(pane)
    assert info.conversation_dir(agent, {}) == str(pane)


def test_safe_dir_rejects_option_like_and_relative_paths(tmp_path):
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
