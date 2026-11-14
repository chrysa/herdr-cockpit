import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "agent-info"))

import worktrees


def git(*args, cwd):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True,
                   env={**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
                        "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"})


def make_repo(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    git("init", "-q", "-b", "main", cwd=repo)
    (repo / "f").write_text("x")
    git("add", "f", cwd=repo)
    git("commit", "-q", "-m", "init", cwd=repo)
    wt = tmp_path / "repo-wt"
    git("worktree", "add", "-q", "-b", "feat", str(wt), cwd=repo)
    return repo, wt


def test_main_checkout_is_not_linked(tmp_path):
    repo, _ = make_repo(tmp_path)
    assert worktrees.checkout_of(str(repo)) is None


def test_linked_worktree_resolves_to_its_checkout(tmp_path):
    _, wt = make_repo(tmp_path)
    assert worktrees.checkout_of(str(wt / ".")) == os.path.realpath(wt)


def test_non_repo_is_ignored(tmp_path):
    assert worktrees.checkout_of(str(tmp_path)) is None


def test_open_linked_opens_unlisted_worktree_once(tmp_path, monkeypatch):
    _, wt = make_repo(tmp_path)
    calls = []

    def herdr(*args):
        calls.append(args)
        return {"result": {"worktrees": []}} if args == ("worktree", "list") else {}

    state = {}
    panes = [{"cwd": str(wt)}]
    monkeypatch.setattr(worktrees, "ENABLED", True)
    worktrees.open_linked(panes, herdr, state)
    worktrees.open_linked(panes, herdr, state)
    assert calls.count(("worktree", "open", "--cwd", os.path.realpath(wt))) == 1


def test_open_linked_skips_listed_worktree(tmp_path, monkeypatch):
    _, wt = make_repo(tmp_path)
    calls = []

    def herdr(*args):
        calls.append(args)
        if args == ("worktree", "list"):
            return {"result": {"worktrees": [{"checkout_path": os.path.realpath(wt)}]}}
        return {}

    monkeypatch.setattr(worktrees, "ENABLED", True)
    worktrees.open_linked([{"cwd": str(wt)}], herdr, {})
    assert all(c[:2] != ("worktree", "open") for c in calls)


def test_disabled_does_nothing(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(worktrees, "ENABLED", False)
    worktrees.open_linked([{"cwd": str(tmp_path)}], lambda *a: calls.append(a), {})
    assert calls == []
