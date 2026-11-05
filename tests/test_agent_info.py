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
                                 "topic_pro": None, "topic_codex": None, "topic_other": None})]


@pytest.mark.parametrize("label, status, wanted", [
    ("api", "working", "◐ api"),
    ("◐ api", "blocked", "‼ api"),
    ("✓ api", "idle", "api"),
    ("‼ ◐ api", "done", "✓ api"),
    ("", "working", ""),
])
def test_tab_label(label, status, wanted):
    assert monitor.tab_label(label, status) == wanted


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


def test_space_theme_prefers_a_blocked_agent_then_the_latest():
    agents = [
        {"pane_id": "a", "workspace_id": "w1", "agent_status": "idle", "state_change_seq": 9, "terminal_title_stripped": "Latest"},
        {"pane_id": "b", "workspace_id": "w1", "agent_status": "blocked", "state_change_seq": 2, "terminal_title_stripped": "Needs you"},
        {"pane_id": "c", "workspace_id": "w1", "agent_status": "working", "state_change_seq": 5, "terminal_title_stripped": "Latest"},
        {"pane_id": "d", "workspace_id": "w2", "agent_status": "idle", "state_change_seq": 3, "terminal_title_stripped": "Old"},
        {"pane_id": "e", "workspace_id": "w2", "agent_status": "done", "state_change_seq": 7, "terminal_title_stripped": "New"},
        {"pane_id": "f", "workspace_id": "w3", "agent_status": "idle", "terminal_title_stripped": "Alone"},
    ]
    spaces = monitor.space_tokens(agents)
    assert spaces["w1"] == {"theme": "Needs you", "more": "+1"}
    assert spaces["w2"] == {"theme": "New", "more": "+1"}
    assert spaces["w3"] == {"theme": "Alone", "more": None}


def test_space_theme_skips_generic_titles_unless_alone():
    agents = [
        {"pane_id": "a", "workspace_id": "w1", "agent_status": "idle", "state_change_seq": 9, "terminal_title_stripped": "claude"},
        {"pane_id": "b", "workspace_id": "w1", "agent_status": "idle", "state_change_seq": 1, "terminal_title_stripped": "Real work"},
        {"pane_id": "c", "workspace_id": "w2", "agent_status": "idle", "terminal_title_stripped": "claude", "agent": "claude"},
    ]
    spaces = monitor.space_tokens(agents)
    assert spaces["w1"] == {"theme": "Real work", "more": None}
    assert spaces["w2"] == {"theme": "claude", "more": None}


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
        ("w1", {"theme": "x", "more": None, **names(space_busy_perso="chrysa")}),
        ("w2", {"theme": None, "more": None, **names(space_idle_pro="padam-av")}),
        ("w1", {"theme": None, "more": None, **names(space_idle_perso="chrysa")}),
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
    monitor.publish_space("w1", {"theme": "Fix\x1b[2J it"})
    args = calls[0]
    assert args[:3] == ("workspace", "report-metadata", "w1")
    assert "theme=Fix[2J it" in args
    cleared = [args[i + 1] for i, a in enumerate(args) if a == "--clear-token"]
    assert set(cleared) == set(monitor.SPACE_TOKENS) - {"theme"}
