import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "cockpit"))

import agent_view  # noqa: E402


def test_no_filter_when_nothing_selected():
    assert agent_view.build_filter(dict(agent_view.NONE)) is None


def test_default_shows_only_the_selected_space(monkeypatch, tmp_path):
    monkeypatch.setattr(agent_view, "STATE", str(tmp_path / "missing.json"))
    assert agent_view.build_filter(agent_view.load()) == {
        "op": "eq", "field": "workspace_id", "value": {"context": "current_workspace_id"}}


def test_reset_shows_every_agent(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(agent_view, "STATE_DIR", str(tmp_path))
    monkeypatch.setattr(agent_view, "STATE", str(tmp_path / "agent-view.json"))
    monkeypatch.setattr(agent_view, "call", lambda method, params: calls.append((method, params)) or {})
    monkeypatch.setattr(sys, "argv", ["agent_view.py", "reset"])
    agent_view.main()
    assert calls[0][0] == "agent.view.clear"
    assert agent_view.load() == agent_view.NONE


def test_single_filter_is_not_wrapped():
    assert agent_view.build_filter({"profile": "pro", "active": False, "space": False}) == {
        "op": "eq", "field": {"token": "account"}, "value": "pro"}


def test_filters_combine_with_all():
    query = agent_view.build_filter({"profile": "", "active": True, "space": True})
    assert query["op"] == "all"
    assert [f["field"] for f in query["filters"]] == ["status", "workspace_id"]


def test_label():
    assert agent_view.label({"profile": "perso", "active": True, "space": False}) == "perso · actifs"
    assert agent_view.label(dict(agent_view.NONE)) == "tous"
    assert agent_view.label(dict(agent_view.DEFAULT)) == "ce space · priorité"


def test_default_keeps_the_native_priority_order(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(agent_view, "STATE", str(tmp_path / "missing.json"))
    monkeypatch.setattr(agent_view, "call", lambda method, params: calls.append((method, params)) or {})
    agent_view.apply(agent_view.load())
    assert calls[-1][1]["sort"] == agent_view.SORT_ATTENTION


def test_space_order_is_explicit_when_filtered(monkeypatch):
    calls = []
    monkeypatch.setattr(agent_view, "call", lambda method, params: calls.append((method, params)) or {})
    agent_view.apply({"profile": "", "active": False, "space": True, "attention": False})
    assert calls[-1][1]["sort"] == agent_view.SORT_SPACES


def test_sort_only_view_keeps_every_agent(monkeypatch):
    calls = []
    monkeypatch.setattr(agent_view, "call", lambda method, params: calls.append((method, params)) or {})
    agent_view.apply({"profile": "", "active": False, "space": False, "attention": True})
    method, params = calls[-1]
    assert method == "agent.view.set"
    assert params["filter"] == {"op": "exists", "field": "pane_id"}
    assert params["sort"][0] == {"field": "attention", "order": "desc"}


def test_apply_waits_for_the_socket_at_startup(monkeypatch):
    attempts = []

    def flaky(state):
        attempts.append(1)
        if len(attempts) < 3:
            raise ConnectionRefusedError("server starting")
        return {"result": {"active": True}}

    monkeypatch.setattr(agent_view, "apply", flaky)
    assert agent_view.apply_when_ready(dict(agent_view.DEFAULT), sleep=lambda s: None) == {"result": {"active": True}}
    assert len(attempts) == 3


def test_apply_gives_up_after_the_wait(monkeypatch):
    monkeypatch.setattr(agent_view, "apply", lambda state: (_ for _ in ()).throw(FileNotFoundError("no socket")))
    try:
        agent_view.apply_when_ready(dict(agent_view.DEFAULT), wait_s=0, sleep=lambda s: None)
    except FileNotFoundError:
        pass
    else:
        raise AssertionError("expected the socket error")


def test_refresh_reapplies_only_after_a_server_restart(monkeypatch, tmp_path):
    sock = tmp_path / "herdr.sock"
    sock.write_text("")
    calls = []
    monkeypatch.setenv("HERDR_SOCKET_PATH", str(sock))
    monkeypatch.setattr(agent_view, "STATE_DIR", str(tmp_path))
    monkeypatch.setattr(agent_view, "STATE", str(tmp_path / "agent-view.json"))
    monkeypatch.setattr(agent_view, "SERVER_MARK", str(tmp_path / "applied-server"))
    monkeypatch.setattr(agent_view, "call", lambda method, params: calls.append(method) or {})
    monkeypatch.setattr(sys, "argv", ["agent_view.py", "refresh"])
    agent_view.main()  # never applied: apply
    agent_view.main()  # same server: nothing, the column keeps its selection
    assert calls == ["agent.view.set"]
    sock.unlink()
    sock.write_text("")  # new server, new socket file
    agent_view.main()
    assert calls == ["agent.view.set", "agent.view.set"]


def test_collapsed_spaces_are_excluded_from_the_column():
    query = agent_view.build_filter({**agent_view.NONE, "collapsed": ["w1", "w2"]})
    assert query == {"op": "not", "filter": {"op": "in", "field": "workspace_id", "values": ["w1", "w2"]}}


def test_collapse_toggles_the_focused_space(monkeypatch, tmp_path):
    spaces = {"result": {"workspaces": [{"workspace_id": "w1", "focused": False}, {"workspace_id": "w2", "focused": True}]}}
    calls = []
    monkeypatch.setattr(agent_view, "STATE_DIR", str(tmp_path))
    monkeypatch.setattr(agent_view, "STATE", str(tmp_path / "agent-view.json"))
    def fake_call(method, params):
        calls.append(method)
        return spaces if method == "workspace.list" else {}

    monkeypatch.setattr(agent_view, "call", fake_call)
    monkeypatch.setattr(agent_view, "notify", lambda state: None)
    monkeypatch.setattr(agent_view, "remember_server", lambda: None)
    monkeypatch.setattr(sys, "argv", ["agent_view.py", "collapse"])
    agent_view.main()
    assert agent_view.load()["collapsed"] == ["w2"]
    assert agent_view.label(agent_view.load()) == "ce space · priorité · 1 replié(s)"
    agent_view.main()
    assert agent_view.load()["collapsed"] == []
    assert calls.count("agent.view.set") + calls.count("agent.view.clear") == 2  # the view follows each toggle


def test_reset_unfolds_every_space(monkeypatch, tmp_path):
    monkeypatch.setattr(agent_view, "STATE_DIR", str(tmp_path))
    monkeypatch.setattr(agent_view, "STATE", str(tmp_path / "agent-view.json"))
    monkeypatch.setattr(agent_view, "call", lambda method, params: {})
    monkeypatch.setattr(agent_view, "notify", lambda state: None)
    monkeypatch.setattr(agent_view, "remember_server", lambda: None)
    agent_view.save({**agent_view.NONE, "collapsed": ["w1"]})
    monkeypatch.setattr(sys, "argv", ["agent_view.py", "reset"])
    agent_view.main()
    assert agent_view.load()["collapsed"] == []


def _attention_calls(monkeypatch, workspaces, agents):
    calls = []

    def fake_call(method, params):
        calls.append((method, params))
        if method == "workspace.list":
            return {"result": {"workspaces": workspaces}}
        if method == "agent.list":
            return {"result": {"agents": agents}}
        return {}

    monkeypatch.setattr(agent_view, "call", fake_call)
    return calls


def test_attention_focuses_the_blocked_agent_of_the_focused_space(monkeypatch):
    calls = _attention_calls(
        monkeypatch,
        [{"workspace_id": "w1", "focused": True}, {"workspace_id": "w2", "focused": False}],
        [{"pane_id": "p1", "workspace_id": "w1", "status": "working", "state_change_seq": 9},
         {"pane_id": "p2", "workspace_id": "w1", "status": "blocked", "state_change_seq": 3},
         {"pane_id": "p3", "workspace_id": "w2", "status": "blocked", "state_change_seq": 7}])
    agent_view.focus_attention()
    assert calls[-1] == ("agent.focus", {"pane_id": "p2"})


def test_attention_takes_the_longest_waiting_agent(monkeypatch):
    calls = _attention_calls(
        monkeypatch,
        [{"workspace_id": "w1", "focused": True}],
        [{"pane_id": "old", "workspace_id": "w1", "status": "blocked", "state_change_seq": 1},
         {"pane_id": "new", "workspace_id": "w1", "status": "blocked", "state_change_seq": 5}])
    agent_view.focus_attention()
    assert calls[-1] == ("agent.focus", {"pane_id": "new"})


def test_attention_without_blocked_agent_only_notifies(monkeypatch):
    calls = _attention_calls(
        monkeypatch,
        [{"workspace_id": "w1", "focused": True}],
        [{"pane_id": "p1", "workspace_id": "w1", "status": "working", "state_change_seq": 1}])
    agent_view.focus_attention()
    assert [m for m, _ in calls] == ["workspace.list", "agent.list", "notification.show"]
