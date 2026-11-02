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
    agents = [{"pane_id": "p1", "agent": "x"}]
    monkeypatch.setattr(monitor, "herdr", lambda *args: {"result": {"agents": agents}} if args[:2] == ("agent", "list") else {})
    monkeypatch.setattr(monitor, "agent_info", lambda agent: ("opus-5.5", "perso"))
    monkeypatch.setattr(monitor, "publish", lambda pane, tokens: published.append((pane, tokens)))
    shown = {"_refreshed": 10 ** 12}
    monitor.tick(shown)
    monitor.tick(shown)
    assert published == [("p1", {"account": "perso", "model": "opus-5.5"})]


@pytest.mark.parametrize("label, status, wanted", [
    ("api", "working", "◐ api"),
    ("◐ api", "blocked", "‼ api"),
    ("✓ api", "idle", "api"),
    ("‼ ◐ api", "done", "✓ api"),
    ("", "working", ""),
])
def test_tab_label(label, status, wanted):
    assert monitor.tab_label(label, status) == wanted


def test_space_tokens_count_agents_attention_and_accounts():
    agents = [
        {"pane_id": "a", "workspace_id": "w1", "agent_status": "blocked"},
        {"pane_id": "b", "workspace_id": "w1", "agent_status": "done"},
        {"pane_id": "c", "workspace_id": "w1", "agent_status": "working"},
        {"pane_id": "d", "workspace_id": "w2", "agent_status": "idle"},
        {"pane_id": "e", "workspace_id": "w2", "agent_status": "idle"},
    ]
    accounts = {"a": "perso", "b": "pro", "c": "perso", "d": "omniroute", "e": None}
    spaces = monitor.space_tokens(agents, accounts)
    assert spaces["w1"] == {"agents": "3 agents", "waiting": "‼1", "done": "✓1",
                            "acc_perso": "perso", "acc_pro": "pro", "acc_codex": None, "acc_other": None}
    assert spaces["w2"] == {"agents": "2 agents", "waiting": None, "done": None,
                            "acc_perso": None, "acc_pro": None, "acc_codex": None, "acc_other": "omniroute"}


def test_space_tokens_singular_and_control_characters():
    agents = [{"pane_id": "a", "workspace_id": "w1", "agent_status": "idle"}]
    assert monitor.space_tokens(agents, {"a": "ev\x1bil"})["w1"]["agents"] == "1 agent"
    assert monitor.space_tokens(agents, {"a": "ev\x1bil"})["w1"]["acc_other"] == "evil"


def test_tick_publishes_space_tokens_and_clears_emptied_spaces(monkeypatch):
    spaces = []
    agents = [{"pane_id": "p1", "workspace_id": "w1", "agent_status": "blocked", "agent": "x"}]
    monkeypatch.setattr(monitor, "herdr", lambda *args: {"result": {"agents": agents}} if args[:2] == ("agent", "list") else {})
    monkeypatch.setattr(monitor, "agent_info", lambda agent: ("opus-5.5", "pro"))
    monkeypatch.setattr(monitor, "publish", lambda pane, tokens: None)
    monkeypatch.setattr(monitor, "publish_space", lambda ws, tokens: spaces.append((ws, tokens)))
    shown = {"_refreshed": 10 ** 12}
    monitor.tick(shown)
    monitor.tick(shown)
    agents.clear()
    monitor.tick(shown)
    assert [ws for ws, _ in spaces] == ["w1", "w1"]
    assert spaces[0][1]["waiting"] == "‼1" and spaces[0][1]["acc_pro"] == "pro"
    assert spaces[1][1] == {}


def test_publish_space_sets_and_clears(monkeypatch):
    calls = []
    monkeypatch.setattr(monitor, "herdr", lambda *args: calls.append(args) or {})
    monitor.publish_space("w1", {"agents": "2 agents"})
    args = calls[0]
    assert args[:3] == ("workspace", "report-metadata", "w1")
    assert "agents=2 agents" in args
    cleared = [args[i + 1] for i, a in enumerate(args) if a == "--clear-token"]
    assert set(cleared) == set(monitor.SPACE_TOKENS) - {"agents"}
