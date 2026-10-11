import header


def test_git_state_clean_and_dirty(tmp_path, monkeypatch):
    import subprocess
    subprocess.run(["git", "init", "-q", "-b", "main", str(tmp_path)], check=True)
    root, state = header.git_state(str(tmp_path))
    assert root == str(tmp_path) and state == "⑂ main ✓"
    (tmp_path / "new.txt").write_text("x")
    assert header.git_state(str(tmp_path))[1] == "⑂ main ?1"


def test_no_git(tmp_path):
    assert header.git_state(str(tmp_path)) == (None, None)


def test_lines_strip_control_characters(tmp_path, monkeypatch):
    monkeypatch.setattr(header.monitor, "agent_info", lambda agent: ("m\x1b[2J", "pro"))
    out = header.lines(str(tmp_path), "claude", "s")
    assert "\x1b[2J" not in "".join(out)
    assert "pro" in out[0]
