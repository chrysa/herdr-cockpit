import json

import pytest

import monitor


@pytest.mark.parametrize("raw, short", [
    ("claude-opus-5-5", "opus-5.5"),
    ("claude-sonnet-4-5-20250929", "sonnet-4.5"),
    ("gpt-6.1-sol", "gpt-6.1-sol"),
])
def test_short_model(raw, short):
    assert monitor.short_model(raw) == short


def test_claude_account_and_model_from_transcript(tmp_path, monkeypatch):
    project = tmp_path / ".claude-pro" / "projects" / "-home-x"
    project.mkdir(parents=True)
    (project / "abc.jsonl").write_text(json.dumps({"message": {"model": "claude-opus-5-5"}}) + "\n")
    monkeypatch.setattr(monitor, "HOME", str(tmp_path))
    assert monitor.claude_info("abc") == ("opus-5.5", "pro")
    assert monitor.claude_info("missing") == (None, None)


def test_opencode_provider_plays_the_account(tmp_path, monkeypatch):
    (tmp_path / "opencode.json").write_text(json.dumps({"model": "omniroute/ai-suush-coding"}))
    assert monitor.opencode_info(str(tmp_path)) == ("ai-suush-coding", "omniroute")


def test_publish_strips_control_characters_and_clears_empty(monkeypatch):
    calls = []
    monkeypatch.setattr(monitor, "herdr", lambda *args: calls.append(args) or {})
    monitor.publish("w1:p1", {"account": "per\x1b[2Jso", "model": None})
    args = calls[0]
    assert "account=per[2Jso" in args
    assert args[args.index("--clear-token") + 1] == "model"


def test_tick_publishes_only_changes(monkeypatch):
    published = []
    agents = [{"pane_id": "p1", "agent": "x", "terminal_title_stripped": "Fix the parser"}]
    monkeypatch.setattr(monitor, "herdr", lambda *args: {"result": {"agents": agents}} if args[:2] == ("agent", "list") else {})
    monkeypatch.setattr(monitor, "agent_info", lambda agent: ("opus-5.5", "perso"))
    monkeypatch.setattr(monitor, "publish", lambda pane, tokens: published.append((pane, tokens)))
    shown = {"_refreshed": 10 ** 12}
    monitor.tick(shown)
    monitor.tick(shown)
    assert published == [("p1", {"account": "perso", "model": "opus-5.5", "topic_perso": "Fix the parser",
                                 "topic_pro": None, "topic_codex": None, "topic_other": None,
                                 "age": None, "doing": None})]


def test_tick_publishes_the_age_of_the_state(monkeypatch):
    published = []
    agents = [{"pane_id": "p1", "agent": "x", "agent_status": "done", "state_change_seq": 4}]
    monkeypatch.setattr(monitor, "herdr", lambda *args: {"result": {"agents": agents}} if args[:2] == ("agent", "list") else {})
    monkeypatch.setattr(monitor, "agent_info", lambda agent: (None, "perso"))
    monkeypatch.setattr(monitor, "publish", lambda pane, tokens: published.append(tokens["age"]))
    shown, state = {"_refreshed": 10 ** 12}, monitor.new_state()
    monitor.tick(shown, state, now=1000)
    monitor.tick(shown, state, now=1000 + 12 * 60)
    agents[0]["state_change_seq"] = 5  # new state: the age starts again
    monitor.tick(shown, state, now=1000 + 13 * 60)
    assert published == [None, "12m", None]


@pytest.mark.parametrize("seconds, label", [(59, None), (60, "1m"), (3599, "59m"), (3900, "1h05"), (2 * 86400, "2j")])
def test_age_label(seconds, label):
    assert monitor.age_label(seconds) == label


def test_since_survives_a_restart(tmp_path, monkeypatch):
    monkeypatch.setattr(monitor, "SINCE", str(tmp_path / "since.json"))
    monitor.save_since({"p1": ["done", 4, 1000.0]})
    assert monitor.load_since() == {"p1": ["done", 4, 1000.0]}
    (tmp_path / "since.json").write_text("not json")
    assert monitor.load_since() == {}


@pytest.mark.parametrize("name, args, text", [
    ("Edit", {"file_path": "/a/b/monitor.py"}, "Edit monitor.py"),
    ("Bash", {"command": "uv run pytest -q", "description": "Run the tests"}, "Bash Run the tests"),
    ("Bash", {"command": "ls\n-la"}, "Bash ls -la"),
    ("Grep", {"pattern": "def tick"}, "Grep def tick"),
    ("WebFetch", {"url": "https://herdr.dev/llms.txt"}, "WebFetch herdr.dev"),
    ("mcp__github__get_issue", {}, "get_issue"),
    ("Bash", {"description": "x" * 60}, "Bash " + "x" * 32 + "…"),
])
def test_describe_tool(name, args, text):
    assert monitor.describe_tool(name, args) == text


def test_last_tool_reads_the_main_thread_tail(tmp_path):
    path = tmp_path / "s.jsonl"
    lines = [
        {"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "Read", "input": {"file_path": "/x/a.py"}}]}},
        {"type": "assistant", "isSidechain": True,
         "message": {"content": [{"type": "tool_use", "name": "Grep", "input": {"pattern": "sub"}}]}},
        {"type": "user", "message": {"content": [{"type": "tool_result", "content": "ok"}]}},
    ]
    path.write_text('{"cut": "tool_use' + "\n" + "\n".join(json.dumps(e) for e in lines) + "\n")
    assert monitor.last_tool(str(path)) == "Read a.py"
    assert monitor.last_tool(str(tmp_path / "missing.jsonl")) is None


def test_doing_only_for_working_claude_agents(monkeypatch):
    monkeypatch.setattr(monitor, "claude_transcript", lambda session: "/t.jsonl")
    monkeypatch.setattr(monitor, "last_tool", lambda path: "Edit a.py")
    agent = {"agent": "claude", "agent_status": "working", "agent_session": {"value": "s1"}}
    assert monitor.agent_doing(agent) == "Edit a.py"
    assert monitor.agent_doing({**agent, "agent_status": "idle"}) is None
    assert monitor.agent_doing({**agent, "agent": "codex"}) is None


def test_notify_blocked_once_never_focused_nor_at_startup(monkeypatch):
    sent = []
    monkeypatch.setattr(monitor, "NOTIFY", True)
    monkeypatch.setattr(monitor, "desktop_notify", lambda title, body: sent.append((title, body)))
    state = monitor.new_state()
    old = {"pane_id": "p0", "workspace_id": "w1", "agent_status": "blocked", "state_change_seq": 1}
    monitor.notify_blocked([old], state, {"w1": "chrysa"})  # first tick: already blocked, no alert
    state["first"] = False
    new = {"pane_id": "p1", "workspace_id": "w1", "agent_status": "blocked", "state_change_seq": 7,
           "terminal_title_stripped": "Needs you"}
    focused = {"pane_id": "p2", "workspace_id": "w1", "agent_status": "blocked", "state_change_seq": 8, "focused": True}
    monitor.notify_blocked([old, new, focused], state, {"w1": "chrysa"})
    monitor.notify_blocked([old, new, focused], state, {"w1": "chrysa"})
    assert sent == [("Agent en attente · chrysa", "Needs you")]
    monitor.notify_blocked([], state, {})
    assert state["notified"] == set()


def test_desktop_notify_escapes_markup(monkeypatch):
    calls = []
    monkeypatch.setattr(monitor.shutil, "which", lambda name: "/bin/notify-send" if name == "notify-send" else None)
    monkeypatch.setattr(monitor.subprocess, "run", lambda cmd, **kw: calls.append(cmd))
    monitor.desktop_notify("Agent · x", "<b>Fix</b> & \x1b[2Jgo")
    monitor.desktop_notify("Agent · x", "-u critical")
    assert calls == [["notify-send", "--app-name=herdr", "--", "Agent · x", "&lt;b&gt;Fix&lt;/b&gt; &amp; [2Jgo"],
                     ["notify-send", "--app-name=herdr", "--", "Agent · x", "-u critical"]]


def test_release_tabs_clears_only_prefixed_names(monkeypatch):
    calls = []
    tabs = [{"tab_id": "t1", "label": "◐ chrysa"}, {"tab_id": "t2", "label": "‼ ✓ api"},
            {"tab_id": "t3", "label": "config"}, {"tab_id": "t4", "label": ""}]

    def fake(*args):
        calls.append(args)
        return {"result": {"tabs": tabs}} if args[:2] == ("tab", "list") else {}

    monkeypatch.setattr(monitor, "herdr", fake)
    monitor.release_tabs()
    assert [c for c in calls if c[:2] == ("tab", "rename")] == [("tab", "rename", "t1", ""), ("tab", "rename", "t2", "")]


@pytest.mark.parametrize("account, key", [
    ("perso", "topic_perso"), ("pro", "topic_pro"), ("codex", "topic_codex"),
    ("omniroute", "topic_other"), (None, "topic_other"),
])
def test_topic_lands_in_the_token_of_its_account(account, key):
    tokens = monitor.topic_tokens({"terminal_title_stripped": "Fix the parser"}, account)
    assert tokens[key] == "Fix the parser"
    assert [k for k, v in tokens.items() if v] == [key]
    assert set(monitor.TOPIC_TOKENS) <= set(monitor.TOKENS)  # publish() clears the others


@pytest.mark.parametrize("agent, topic", [
    ({"terminal_title_stripped": "Fix\x1b[2J it", "title": "other"}, "Fix[2J it"),
    ({"terminal_title_stripped": "", "title": "Session title"}, "Session title"),
    ({"terminal_title_stripped": "claude", "title": "Session title"}, "Session title"),
    ({"terminal_title_stripped": "claude", "agent": "claude"}, "claude"),
    ({"agent": "codex"}, "codex"),
])
def test_topic_prefers_a_real_title(agent, topic):
    assert monitor.topic_tokens(agent, "perso")["topic_perso"] == topic


def waits(*lines, more=None):
    return {**{f"wait{i}": lines[i - 1] if i <= len(lines) else None for i in range(1, monitor.WAIT_ROWS + 1)},
            "wait_more": more}


def test_spaces_list_only_waiting_agents_longest_wait_first():
    agents = [
        {"pane_id": "a", "workspace_id": "w1", "agent_status": "working", "state_change_seq": 9, "terminal_title_stripped": "Busy"},
        {"pane_id": "b", "workspace_id": "w1", "agent_status": "blocked", "state_change_seq": 5, "terminal_title_stripped": "Later"},
        {"pane_id": "c", "workspace_id": "w1", "agent_status": "blocked", "state_change_seq": 2, "terminal_title_stripped": "First"},
        {"pane_id": "d", "workspace_id": "w2", "agent_status": "done", "state_change_seq": 7, "terminal_title_stripped": "Done"},
    ]
    spaces = monitor.space_tokens(agents)
    assert spaces["w1"] == waits("‼ First", "‼ Later")
    assert spaces["w2"] == waits()


def test_spaces_cap_waiting_lines():
    agents = [{"pane_id": f"p{i}", "workspace_id": "w1", "agent_status": "blocked", "state_change_seq": i,
               "terminal_title_stripped": f"T{i}"} for i in range(5)]
    assert monitor.space_tokens(agents)["w1"] == waits("‼ T0", "‼ T1", "‼ T2", more="+2 en attente")


def names(**set_):
    return {name: set_.get(name) for name in monitor.NAME_TOKENS}


def test_tick_publishes_space_tokens_and_clears_emptied_spaces(monkeypatch):
    spaces = []
    agents = [{"pane_id": "p1", "workspace_id": "w1", "agent_status": "blocked", "agent": "x"}]
    workspaces = [{"workspace_id": "w1", "label": "chrysa"}, {"workspace_id": "w2", "label": "padam-av"}]
    replies = {("agent", "list"): {"result": {"agents": agents}},
               ("workspace", "list"): {"result": {"workspaces": workspaces}}}
    monkeypatch.setattr(monitor, "herdr", lambda *args: replies.get(args[:2], {}))
    monkeypatch.setattr(monitor, "agent_info", lambda agent: ("opus-5.5", "pro"))
    monkeypatch.setattr(monitor, "publish", lambda pane, tokens: None)
    monkeypatch.setattr(monitor, "publish_space", lambda ws, tokens: spaces.append((ws, tokens)))
    shown = {"_refreshed": 10 ** 12}
    monitor.tick(shown)
    monitor.tick(shown)  # unchanged: nothing republished
    agents.clear()
    monitor.tick(shown)
    workspaces.pop()
    monitor.tick(shown)
    assert spaces == [
        ("w1", {**waits("‼ x"), **names(space_busy_perso="chrysa")}),
        ("w2", {**waits(), **names(space_idle_pro="padam-av")}),
        ("w1", {**waits(), **names(space_idle_perso="chrysa")}),
        ("w2", {}),  # space closed: tokens cleared
    ]


@pytest.mark.parametrize("label, eco", [
    ("padam-av", "pro"), ("padam-av-GHA", "pro"), ("chrysa", "perso"), ("chrysa-x", "other"), ("heya", "other"),
])
def test_ecosystem(label, eco):
    assert monitor.ecosystem(label) == eco


def test_short_name_drops_the_longest_parent_prefix():
    labels = ["padam-av", "padam-av-GHA", "padam-av-GHA-ci", "heya", "padam"]
    assert monitor.short_name("padam-av-GHA", labels) == "↳ GHA"
    assert monitor.short_name("padam-av-GHA-ci", labels) == "↳ ci"
    assert monitor.short_name("padam-av", labels) == "↳ av"
    assert monitor.short_name("heya", labels) == "heya"


def test_name_tokens_set_exactly_one():
    tokens = monitor.name_tokens("padam-av-GHA", ["padam-av", "padam-av-GHA"], busy=False)
    assert tokens == names(space_idle_pro="↳ GHA")
    assert monitor.name_tokens("", [""], busy=True) == names()


def test_publish_space_sets_and_clears(monkeypatch):
    calls = []
    monkeypatch.setattr(monitor, "herdr", lambda *args: calls.append(args) or {})
    monitor.publish_space("w1", {"wait1": "Fix\x1b[2J it"})
    args = calls[0]
    assert args[:3] == ("workspace", "report-metadata", "w1")
    assert "wait1=Fix[2J it" in args
    cleared = [args[i + 1] for i, a in enumerate(args) if a == "--clear-token"]
    assert set(cleared) == set(monitor.SPACE_TOKENS) - {"wait1"}
