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
