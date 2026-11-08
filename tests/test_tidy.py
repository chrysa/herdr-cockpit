import json

import tidy

DAY = 24 * 3600
NOW = 1_800_000_000.0
RULE = "─" * 20


def screen(prompt_line):
    return f"❯ old question shown in the history\nanswer\n{RULE}\n{prompt_line}\n{RULE}\n  ● perso  footer"


def test_prompt_empty_ignores_claude_codes_dim_suggestion():
    assert tidy.prompt_empty(screen("❯\xa0"))
    assert tidy.prompt_empty(screen("❯\xa0\x1b[0m\x1b[2mcommit le lock\x1b[0m\r"))
    assert not tidy.prompt_empty(screen("❯ half-typed question"))
    assert not tidy.prompt_empty("no prompt on screen")


def agent(pane, status="idle", **extra):
    return {"pane_id": pane, "agent": "claude", "agent_status": status, "tab_id": f"t-{pane}", "workspace_id": "w1",
            **extra}


def test_idle_to_close_takes_only_long_idle_unfocused_agents_without_subtasks():
    agents = [agent("old"), agent("recent"), agent("busy", "working"), agent("focused", focused=True),
              agent("in_tab"), agent("subs"), {**agent("codex"), "agent": "codex"}]
    since = {p: ["idle", 1, NOW - 2 * DAY] for p in ("old", "focused", "in_tab", "subs", "codex")}
    since |= {"recent": ["idle", 1, NOW - 3600], "busy": ["working", 1, NOW - 2 * DAY]}
    found = tidy.idle_to_close(agents, since, {"subs": ["running"]}, "t-in_tab", NOW, hours=24)
    assert [a["pane_id"] for a in found] == ["old"]
    assert tidy.idle_to_close(agents, since, {}, None, NOW, hours=0) == []


def test_close_idle_quits_with_ctrl_c_only_on_an_empty_prompt():
    calls = []
    still = iter([True, False])

    def herdr(*args):
        calls.append(args)
        if args[:2] == ("pane", "process-info"):
            names = ["claude"] if next(still) else ["zsh"]
            return {"result": {"process_info": {"foreground_processes": [{"name": n} for n in names]}}}
        return {}

    assert tidy.close_idle(agent("p1"), herdr, lambda *a: screen("❯\xa0"), wait=lambda s: None)
    assert ("pane", "send-keys", "p1", "ctrl+c", "ctrl+c") in calls
    calls.clear()
    assert not tidy.close_idle(agent("p1"), herdr, lambda *a: screen("❯ draft"), wait=lambda s: None)
    assert calls == []


def test_repo_root_only_below_the_space_folder(tmp_path):
    (tmp_path / "repo" / ".git").mkdir(parents=True)
    (tmp_path / "repo" / "src").mkdir()
    assert tidy.repo_root(str(tmp_path / "repo" / "src"), str(tmp_path)) == str(tmp_path / "repo")
    assert tidy.repo_root(str(tmp_path / "repo"), str(tmp_path / "repo")) is None  # the space's own repo
    assert tidy.repo_root(str(tmp_path / "elsewhere"), str(tmp_path)) is None


def test_tab_moves_single_agent_tabs_to_their_repos_space():
    pane = lambda pid, tab, cwd: {"pane_id": pid, "tab_id": tab, "cwd": cwd, "foreground_cwd": cwd}
    panes = [pane("a", "t1", "/p/root/lint"), pane("panel", "t1", tidy.PLUGINS + "/agent-panel/x"),
             pane("b", "t2", "/p/root/viz"), pane("c", "t3", "/p/root/lint"), pane("c2", "t3", "/p/root"),
             pane("d", "t4", "/p/root/lint"), pane("e", "t5", "/p/root/lint")]
    agents = [{"pane_id": p, "agent": "claude", "agent_status": "idle", "workspace_id": "w1"} for p in "abcd"]
    agents.append({"pane_id": "e", "agent": "claude", "agent_status": "blocked", "workspace_id": "w1"})
    folders = {"w1": "/p/root", "w2": "/p/root/lint"}
    roots = {"/p/root/lint": "/p/root/lint", "/p/root/viz": "/p/root/viz"}
    moves = tidy.tab_moves(agents, panes, folders, "t4", root_of=lambda path, stop: roots.get(path))
    # a: agent-panel's pane does not count; c: two panes; d: focused tab; e: waits on you
    assert moves == [("a", "w2", "/p/root/lint"), ("b", None, "/p/root/viz")]


def test_run_closes_moves_logs_and_notifies_once(tmp_path, monkeypatch):
    agents = [agent("old", cwd="/p", agent_session={"value": "s-1"}), agent("mover")]
    since = {"old": ["idle", 1, NOW - 2 * DAY], "mover": ["idle", 1, NOW]}
    panes = [{"pane_id": "old", "tab_id": "t-old", "cwd": "/p"}, {"pane_id": "mover", "tab_id": "t-mover", "cwd": "/p/r"}]
    workspaces = [{"workspace_id": "w1", "label": "chrysa", "focused": True, "active_tab_id": "t-x"}]
    calls, notes = [], []

    def herdr(*args):
        calls.append(args)
        return {"result": {"process_info": {"foreground_processes": [{"name": "zsh"}]}}}

    log = tmp_path / "closed.jsonl"
    monkeypatch.setattr(tidy, "repo_root", lambda path, stop: "/p/r" if path == "/p/r" else None)
    monkeypatch.setattr(tidy.time, "sleep", lambda s: None)
    state = {}
    args = (agents, panes, workspaces, {"w1": "/p"}, since, {}, {"old": "Old one"}, state)
    tail = (herdr, lambda *a: screen("❯\xa0"), lambda t, b: notes.append(t), str(log))
    closed, moved = tidy.run(*args, NOW, *tail)
    again = tidy.run(*args, NOW + 60, *tail)  # tried already: nothing twice
    assert closed == ["Old one"] and moved == ["mover → r"]
    assert again == ([], [])
    assert ("pane", "move", "mover", "--new-workspace", "--label", "r", "--no-focus") in calls
    assert len(notes) == 2
    entry = json.loads(log.read_text())
    assert (entry["space"], entry["session"]) == ("chrysa", "s-1")
