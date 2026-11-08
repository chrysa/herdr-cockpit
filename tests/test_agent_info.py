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
    # no state reported: idle, so no icon and the name under topic_idle (dim grey)
    assert published == [("p1", {"account": "perso", "model": "opus-5.5", "agent_icon": None,
                                 "topic_perso": None, "topic_pro": None, "topic_codex": None, "topic_other": None,
                                 "topic_idle": "Fix the parser", "age": None, "doing": None,
                                 **dict.fromkeys(monitor.SUB_TOKENS)})]


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


def rename_calls(monkeypatch, tabs):
    calls = []

    def fake(*args):
        calls.append(args)
        return {"result": {"tabs": tabs}} if args[:2] == ("tab", "list") else {}

    monkeypatch.setattr(monitor, "herdr", fake)
    return calls


def test_mark_tabs_marks_only_blocked_tabs(monkeypatch):
    tabs = [{"tab_id": "t1", "label": "audit", "agent_status": "blocked"},
            {"tab_id": "t2", "label": "Améliorations", "agent_status": "blocked"},
            {"tab_id": "t3", "label": "vscode", "agent_status": "working"},
            {"tab_id": "t4", "label": "", "agent_status": "blocked"},
            {"tab_id": "t5", "label": "‼ done already", "agent_status": "blocked"}]
    calls, marked = rename_calls(monkeypatch, tabs), {}
    assert monitor.mark_tabs(tabs, marked, hand={"t1"}) is True
    assert calls == [("tab", "rename", "t1", "‼ audit"), ("tab", "rename", "t2", "‼ Améliorations")]
    assert marked == {"t1": "hand", "t2": "auto"}


def test_unmark_gives_hand_names_back_and_auto_names_to_auto_title(monkeypatch):
    tabs = [{"tab_id": "t1", "label": "‼ audit", "agent_status": "working"},
            {"tab_id": "t2", "label": "‼ Améliorations", "agent_status": "done"},
            {"tab_id": "t3", "label": "‼ unknown", "agent_status": "idle"}]
    calls, marked = rename_calls(monkeypatch, tabs), {"t1": "hand", "t2": "auto", "gone": "auto"}
    monitor.mark_tabs(tabs, marked, hand=set())
    assert calls == [("tab", "rename", "t1", "audit"),
                     ("tab", "rename", "t2", ""),  # cleared: auto-title names it afresh
                     ("tab", "rename", "t3", "unknown")]  # not ours on record: keep the name
    assert marked == {}


def test_hand_named_reads_auto_title_locks(tmp_path, monkeypatch):
    monkeypatch.setattr(monitor, "AUTO_TITLE_DIR", str(tmp_path))
    (tmp_path / "manual-names.json").write_text('{"locked_tabs": {"w1:t1": "audit"}}')
    assert monitor.hand_named() == {"w1:t1"}
    custom = tmp_path / "custom.json"
    custom.write_text('{"locked_tabs": {"w2:t1": "x"}}')
    (tmp_path / "config.env").write_text(f"# c\nHERDR_AUTO_TITLE_MANUAL_FILE={custom}\n")
    assert monitor.hand_named() == {"w2:t1"}
    custom.write_text("not json")
    assert monitor.hand_named() == set()


def test_agent_name_ignores_the_mark():
    assert monitor.agent_name({"terminal_title_stripped": "Long title"}, "‼ audit") == "audit"


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


def waits(*lines, more=None, icon=None, **counts):
    return {"space_icon": icon, **{f"wait{i}": lines[i - 1] if i <= len(lines) else None for i in range(1, monitor.WAIT_ROWS + 1)},
            "wait_more": more, **{f"count_{name}": counts.get(name) for name in ("perso", "pro", "codex", "other")}}


def test_spaces_list_only_waiting_agents_longest_wait_first():
    agents = [
        {"pane_id": "a", "workspace_id": "w1", "agent_status": "working", "state_change_seq": 9, "terminal_title_stripped": "Busy"},
        {"pane_id": "b", "workspace_id": "w1", "agent_status": "blocked", "state_change_seq": 5, "terminal_title_stripped": "Later"},
        {"pane_id": "c", "workspace_id": "w1", "agent_status": "blocked", "state_change_seq": 2, "terminal_title_stripped": "First"},
        {"pane_id": "d", "workspace_id": "w2", "agent_status": "done", "state_change_seq": 7, "terminal_title_stripped": "Done"},
    ]
    spaces = monitor.space_tokens(agents)
    assert spaces["w1"] == waits("‼ First", "‼ Later", icon="‼", other="‼2 ◐1")
    assert spaces["w2"] == waits(icon="✓", other="✓1")


def test_space_icon_only_for_working_waiting_or_done():
    def icon(*statuses):
        agents = [{"pane_id": f"p{i}", "workspace_id": "w1", "agent_status": s} for i, s in enumerate(statuses)]
        return monitor.space_tokens(agents)["w1"]["space_icon"]
    assert icon("idle", "unknown") is None
    assert icon("idle", "done") == "✓"
    assert icon("done", "working") == "◐"
    assert icon("working", "blocked", "idle") == "‼"


def test_icon_when_only_subagents_or_tasks_work():
    agents = [{"pane_id": "a", "workspace_id": "w1", "agent_status": "idle"},
              {"pane_id": "b", "workspace_id": "w2", "agent_status": "done"},
              {"pane_id": "c", "workspace_id": "w3", "agent_status": "working"},
              {"pane_id": "d", "workspace_id": "w4", "agent_status": "idle"}]
    details = {"a": {"subs": ["running"]}, "b": {"subs": ["running", "done"]}, "c": {"subs": ["running"]},
               "d": {"subs": ["done"]}}
    icons = {ws: tokens["space_icon"] for ws, tokens in monitor.space_tokens(agents, details).items()}
    assert icons == {"w1": "⑂", "w2": "⑂", "w3": "◐", "w4": None}  # ⑂ outranks ✓, not ◐


def test_spaces_cap_waiting_lines():
    agents = [{"pane_id": f"p{i}", "workspace_id": "w1", "agent_status": "blocked", "state_change_seq": i,
               "terminal_title_stripped": f"T{i}"} for i in range(5)]
    assert monitor.space_tokens(agents)["w1"] == waits("‼ T0", "‼ T1", "‼ T2", more="+2 en attente", icon="‼", other="‼5")


def names(**set_):
    """Child icon, name and group-header tokens of one space, all None but set_."""
    return {name: set_.get(name) for name in (monitor.CHILD_ICON, *monitor.NAME_TOKENS, *monitor.GROUP_TOKENS)}


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
    shown, state = {"_refreshed": 10 ** 12}, monitor.new_state()
    monitor.tick(shown, state)
    monitor.tick(shown, state)  # unchanged: nothing republished
    agents.clear()
    monitor.tick(shown, state)
    workspaces.pop()
    monitor.tick(shown, state)
    assert spaces == [
        # colors from the agents' account (pro here), not the name; no agent ever: grey
        ("w1", {**waits("‼ x", icon="‼", pro="‼1"), **names(space_busy_pro="chrysa")}),
        ("w2", {**waits(), **names(space_idle_other="padam-av")}),
        ("w1", {**waits(), **names(space_idle_pro="chrysa")}),  # agent gone: color kept
        ("w2", {}),  # space closed: tokens cleared
    ]


def test_space_color_comes_from_the_accounts_of_its_agents():
    ids = ["w1", "w2", "w3", "w4", "w5", "w6"]
    parents = {"w3": "w2", "w4": "w3"}
    accounts = {"w1": ["pro", "perso", "pro"], "w2": ["perso"], "w5": ["codex", None], "w6": [None]}
    memory = {"gone": "pro"}
    ecos = monitor.space_ecosystems(ids, parents, accounts, memory)
    # majority; nearest parent's for spaces without agents; codex or unknown accounts: grey
    assert ecos == {"w1": "pro", "w2": "perso", "w3": "perso", "w4": "perso", "w5": "other", "w6": "other"}
    assert memory == {"w1": "pro", "w2": "perso", "w5": "other"}  # closed space dropped
    assert monitor.space_ecosystems(ids, parents, {}, memory)["w1"] == "pro"  # agents gone: kept


def test_short_name_drops_the_parent_prefix():
    assert monitor.short_name("padam-av-GHA", "padam-av") == "GHA"
    assert monitor.short_name("plateform_socle", "Forge-Stack-Workshop") == "plateform_socle"
    assert monitor.short_name("heya", None) == "heya"


B = monitor.INDENT


def test_near_words_allow_one_letter_of_difference():
    assert monitor.near("plateform", "platform") and monitor.near("platform", "plateform")
    assert monitor.near("charts", "chartz") and monitor.near("simul", "simul")
    assert not monitor.near("socle", "social") and not monitor.near("gha", "ghb")


def test_siblings_sharing_a_first_word_get_a_header_row():
    spaces = [("w1", "Forge-Stack-Workshop", "/f"), ("w2", "plateform_socle", "/f/a"),
              ("w3", "plateform_service_catalog", "/f/b"), ("w4", "platform-charts", "/f/c"),
              ("w5", "plateform", "/f/d"), ("w6", "padam-av", "/p"), ("w7", "padam-av-GHA", "/q"),
              ("w8", "a_b", "/f/e"), ("w9", "a_b_c", "/f/g"), ("w10", "plateform_x", "/elsewhere")]
    parents = {"w2": "w1", "w3": "w1", "w4": "w1", "w5": "w1", "w7": "w6", "w8": "w1", "w9": "w1"}
    groups = monitor.sibling_groups(spaces, parents)
    assert groups == {"w2": ("plateform", "socle"), "w3": ("plateform", "service_catalog"),
                      "w4": ("plateform", "charts"),  # one letter apart: one group
                      "w8": ("a", "b"), "w9": ("a", "b_c")}  # short words group only when equal
    order, shown, headers = monitor.space_tree(spaces, parents, groups)
    assert order == ["w1", "w8", "w9", "w5", "w4", "w3", "w2", "w6", "w7", "w10"]
    # w8 and w4 carry their group's header: their name is a second row, which herdr
    # indents by 2 columns itself, so their prefix drops its first unit
    assert shown == {"w1": "Forge-Stack-Workshop", "w8": "├ b", "w9": "│ └ b_c", "w5": "├ plateform",
                     "w4": "├ charts", "w3": f"{B}├ service_catalog", "w2": f"{B}└ socle",
                     "w6": "padam-av", "w7": "└ GHA", "w10": "plateform_x"}
    assert headers == {"w8": "├ a", "w4": "└ plateform"}


def test_a_group_shares_every_leading_word_its_members_have_in_common():
    spaces = [("w1", "p", "/p"), ("w2", "front_web_app", "/p/a"), ("w3", "front_web_admin", "/p/b")]
    groups = monitor.sibling_groups(spaces, {"w2": "w1", "w3": "w1"})
    assert groups == {"w2": ("front_web", "app"), "w3": ("front_web", "admin")}


def test_group_members_sit_together_sorted_by_name():
    spaces = [("w1", "p", "/p"), ("w2", "x_socle", "/p/a"), ("w3", "m", "/p/m"), ("w4", "x_charts", "/p/b")]
    parents = {"w2": "w1", "w3": "w1", "w4": "w1"}
    groups = {"w2": ("x", "socle"), "w4": ("x", "charts")}
    order, shown, headers = monitor.space_tree(spaces, parents, groups)
    assert order == ["w1", "w3", "w4", "w2"]
    assert shown["w3"] == "├ m" and headers == {"w4": "└ x"}


def test_group_tokens_set_exactly_one():
    assert monitor.group_tokens("└ plateform", "other") == {"group_pro": None, "group_perso": None,
                                                            "group_other": "└ plateform"}
    assert set(monitor.group_tokens(None, "pro").values()) == {None}


def test_name_tokens_set_exactly_one():
    only_names = {name: None for name in monitor.NAME_TOKENS}
    assert monitor.name_tokens("└ GHA", "pro", busy=False) == {**only_names, "space_idle_pro": "└ GHA"}
    assert monitor.name_tokens("", "other", busy=True) == only_names


def test_space_folders_prefer_the_pane_named_like_the_space():
    workspaces = [{"workspace_id": "w1", "label": "padam-av"}, {"workspace_id": "w2", "label": "renamed"},
                  {"workspace_id": "w3", "label": "empty"}]
    panes = [{"workspace_id": "w1", "cwd": "/d/padam"}, {"workspace_id": "w1", "cwd": "/d/padam/padam-av/"},
             {"workspace_id": "w2", "cwd": "/d/x/src"}, {"workspace_id": "w2", "cwd": "/d/x"},
             {"workspace_id": "w2", "cwd": "/d/x/src"}]
    assert monitor.space_folders(workspaces, panes) == {"w1": "/d/padam/padam-av", "w2": "/d/x/src", "w3": None}


FSW = "/p/Forge-Stack-Workshop"
SPACES = [("w1", "chrysa", "/p/chrysa"), ("w2", "Forge-Stack-Workshop", FSW), ("w3", "padam-av", "/d/padam-av"),
          ("w4", "padam-av-GHA", "/d/padam-av-GHA"), ("w5", "plateform_socle", f"{FSW}/plateform_socle"),
          ("w6", "platform-charts", f"{FSW}/platform-charts"), ("w7", "deep", f"{FSW}/platform-charts/deep"),
          ("w8", "chrysa-site", None)]


def test_space_parents_by_folder_then_by_name():
    assert monitor.space_parents(SPACES) == {"w4": "w3", "w5": "w2", "w6": "w2", "w7": "w6", "w8": "w1"}


def test_a_name_parent_inside_the_folder_parent_is_more_specific():
    spaces = [("w1", "padam-av-and-more", "/d/padam"), ("w2", "padam-av", "/d/padam/padam-av"),
              ("w3", "padam-av-GHA", "/d/padam/padam-av-GHA"), ("w4", "padam-k8s", "/d/padam/padam-k8s"),
              ("w5", "padam-av", "/d/padam/padam-av")]  # same name and folder as w2: w2, listed first, wins
    parents = monitor.space_parents(spaces)
    assert parents == {"w2": "w1", "w3": "w2", "w4": "w1", "w5": "w1"}
    _, shown, headers = monitor.space_tree(spaces, parents, monitor.sibling_groups(spaces, parents))
    assert shown == {"w1": "padam-av-and-more", "w2": "├ av", "w5": "├ av", "w3": "│ └ GHA", "w4": "└ k8s"}
    assert headers == {}


def test_short_name_drops_the_words_shared_with_the_parent():
    assert monitor.short_name("padam-k8s", "padam-av-and-more") == "k8s"
    assert monitor.short_name("padam-av", "padam-av-and-more") == "av"  # the last word stays
    assert monitor.short_name("Chrysa-site", "chrysa") == "site"


def test_space_parents_skip_a_name_link_that_closes_a_loop():
    spaces = [("w1", "a-b", "/x"), ("w2", "a", "/x/a")]  # w2 lives in w1's folder, w1 is named after w2
    assert monitor.space_parents(spaces) == {"w2": "w1"}


def test_spaces_sorted_alphabetically_children_under_their_parent_as_a_tree():
    ids = ["w1", "w2", "w3", "w4", "w5", "w6", "w7", "w8"]
    parents = monitor.space_parents(SPACES)
    wanted, shown, headers = monitor.space_tree(SPACES, parents, monitor.sibling_groups(SPACES, parents))
    assert wanted == ["w1", "w8", "w2", "w6", "w7", "w5", "w3", "w4"]
    assert shown == {"w1": "chrysa", "w8": "└ site", "w2": "Forge-Stack-Workshop", "w6": "├ charts",
                     "w7": f"{B}│ └ deep", "w5": f"{B}└ socle", "w3": "padam-av", "w4": "└ GHA"}
    assert headers == {"w6": "└ plateform"}
    moves = monitor.moves_to(ids, wanted)
    order = list(ids)
    for ws, index in moves:  # replay as herdr does: index = final place
        order.remove(ws)
        order.insert(index, ws)
    assert order == wanted
    assert monitor.moves_to(wanted, wanted) == []


def test_tick_groups_spaces_by_folder(monkeypatch):
    spaces, moved = [], []
    workspaces = [{"workspace_id": "w1", "label": "Forge-Stack-Workshop"}, {"workspace_id": "w2", "label": "padam-av"},
                  {"workspace_id": "w3", "label": "plateform_socle"}]
    panes = [{"workspace_id": "w1", "cwd": FSW}, {"workspace_id": "w2", "cwd": "/d/padam-av"},
             {"workspace_id": "w3", "cwd": f"{FSW}/plateform_socle"}]
    replies = {("agent", "list"): {"result": {"agents": []}}, ("pane", "list"): {"result": {"panes": panes}},
               ("workspace", "list"): {"result": {"workspaces": workspaces}}}
    monkeypatch.setattr(monitor, "herdr", lambda *args: replies.get(args[:2], {}))
    monkeypatch.setattr(monitor, "publish_space", lambda ws, tokens: spaces.append((ws, tokens)))
    monkeypatch.setattr(monitor, "request", lambda method, params: moved.append((method, params)) or {})
    state = monitor.new_state()
    monitor.tick({"_refreshed": 10 ** 12}, state)
    assert dict(spaces)["w3"] == {**waits(), **names(space_idle_other="└ plateform_socle")}
    assert moved == [("workspace.move", {"workspace_id": "w3", "insert_index": 1})]
    monitor.tick({"_refreshed": 10 ** 12}, state)  # herdr did not take it: not asked again
    assert len(moved) == 1
    workspaces.insert(1, workspaces.pop())
    monitor.tick({"_refreshed": 10 ** 12}, state)  # grouped now; a later move away is undone again
    workspaces.append(workspaces.pop(1))
    monitor.tick({"_refreshed": 10 ** 12}, state)
    assert len(moved) == 2


def test_publish_space_sets_and_clears(monkeypatch):
    calls = []
    monkeypatch.setattr(monitor, "herdr", lambda *args: calls.append(args) or {})
    monitor.publish_space("w1", {"wait1": "Fix\x1b[2J it"})
    assert all(args[:3] == ("workspace", "report-metadata", "w1") for args in calls)
    named = [[args[i + 1] for i, a in enumerate(args) if a in ("--token", "--clear-token")] for args in calls]
    assert all(len(names) <= monitor.REPORT_MAX for names in named)  # herdr refuses more
    args = [a for call in calls for a in call]
    assert "wait1=Fix[2J it" in args
    cleared = [args[i + 1] for i, a in enumerate(args) if a == "--clear-token"]
    assert sorted(cleared) == sorted(set(monitor.SPACE_TOKENS) - {"wait1"})


def test_space_counts_group_agents_and_subagents_by_account():
    agents = [
        {"pane_id": "a", "workspace_id": "w1", "agent_status": "working"},
        {"pane_id": "b", "workspace_id": "w1", "agent_status": "idle"},
        {"pane_id": "c", "workspace_id": "w1", "agent_status": "done"},
        {"pane_id": "d", "workspace_id": "w1", "agent_status": "idle"},
    ]
    details = {"a": {"account": "perso", "subs": ["running", "running", "done"]},
               "b": {"account": "perso", "subs": []},
               "c": {"account": "pro", "subs": ["failed"]},
               "d": {"account": "default", "subs": []}}
    tokens = monitor.space_tokens(agents, details)["w1"]
    assert {k: v for k, v in tokens.items() if k.startswith("count_")} == {
        "count_perso": "◐1 ○1 ⑂●2✓1", "count_pro": "✓1 ⑂✗1", "count_codex": None, "count_other": "○1"}


def test_idle_spaces_count_their_idle_agents():
    agents = [{"pane_id": "a", "workspace_id": "w1", "agent_status": "idle"},
              {"pane_id": "b", "workspace_id": "w1", "agent_status": "idle"},
              {"pane_id": "c", "workspace_id": "w2", "agent_status": "idle"},
              {"pane_id": "d", "workspace_id": "w2", "agent_status": "working"}]
    details = {p: {"account": "perso"} for p in "abcd"}
    tokens = monitor.space_tokens(agents, details)
    assert tokens["w1"]["count_perso"] == "○2"
    assert tokens["w2"]["count_perso"] == "◐1 ○1"


def test_sub_tokens_list_then_overflow():
    statuses = ["running", "stalled"] + ["done"] * monitor.SUB_ROWS
    subs = [{"status": s, "description": f"S{i}"} for i, s in enumerate(statuses)]
    tokens = monitor.sub_tokens(subs)
    assert (tokens["sub1"], tokens["sub2"], tokens["sub3"]) == ("⑂ ● S0", "⑂ ◌ S1", "⑂ ✓ S2")
    assert tokens[f"sub{monitor.SUB_ROWS}"] == f"⑂ ✓ S{monitor.SUB_ROWS - 1}"
    assert tokens["sub_more"] == "⑂ +2"
    assert monitor.sub_tokens([]) == dict.fromkeys(monitor.SUB_TOKENS)


def test_agent_icon_only_when_working_waiting_done_or_subtasks_run():
    icon = lambda status, subs=(): monitor.agent_icon({"agent_status": status}, list(subs))
    assert (icon("blocked", ["running"]), icon("working"), icon("done"), icon("idle"), icon(None)) == ("‼", "◐", "✓", None, None)
    assert (icon("idle", ["running"]), icon("done", ["running"]), icon("idle", ["done"])) == ("⑂", "⑂", None)


def test_idle_agent_name_goes_grey():
    agent = {"terminal_title_stripped": "Fix the parser"}
    assert monitor.topic_tokens(agent, "pro", idle=True) == {
        "topic_perso": None, "topic_pro": None, "topic_codex": None, "topic_other": None, "topic_idle": "Fix the parser"}
    assert monitor.topic_tokens(agent, "pro")["topic_pro"] == "Fix the parser"


def test_agent_tokens_go_out_in_reports_of_at_most_16(monkeypatch):
    calls = []
    monkeypatch.setattr(monitor, "herdr", lambda *args: calls.append(args))
    monitor.publish("p1", {"agent_icon": "◐", "sub13": "⑂ ● last"})
    assert len(calls) == -(-len(monitor.TOKENS) // monitor.REPORT_MAX)
    named = [a for args in calls for a in args if a.startswith(tuple(f"{t}=" for t in monitor.TOKENS))
             or a in monitor.TOKENS]
    assert sorted(a.split("=")[0] for a in named) == sorted(monitor.TOKENS)
    assert all(sum(a in ("--token", "--clear-token") for a in args) <= monitor.REPORT_MAX for args in calls)


@pytest.mark.parametrize("tab, shared, name", [
    ("herdr", False, "herdr"),  # named by hand: the tab's name
    ("Herdr, space et chat inversé", False, "Herdr, space et chat inversés"),  # auto-title cut it
    ("padam › Herdr, space et chat", False, "Herdr, space et chat inversés"),  # auto-title context › activity
    ("Herdr", False, "Herdr"),  # short hand name that starts the title stays
    ("", False, "Herdr, space et chat inversés"),
    ("claude", False, "Herdr, space et chat inversés"),
    ("3", False, "Herdr, space et chat inversés"),
    ("herdr", True, "herdr · Herdr, space et chat inversés"),  # several agents in the tab
    ("prism-ai-lint › main › Gain", False, "prism-ai-lint › Gain"),  # default branch dropped
    ("dev-nexus › develop › S4 loop", False, "dev-nexus › S4 loop"),
    ("chrysa › feat/x › Audit", False, "chrysa › feat/x › Audit"),  # a work branch stays
    ("main › Gain", False, "main › Gain"),  # only a middle segment is a branch
    ("develop", False, "Herdr, space et chat inversés"),  # a bare default branch is generic
])
def test_agent_name_follows_the_tab(tab, shared, name):
    agent = {"terminal_title_stripped": "Herdr, space et chat inversés"}
    assert monitor.agent_name(agent, tab, shared) == name


def test_agent_names_marks_shared_tabs():
    agents = [{"pane_id": "a", "tab_id": "t1", "terminal_title_stripped": "One"},
              {"pane_id": "b", "tab_id": "t1", "terminal_title_stripped": "Two"},
              {"pane_id": "c", "tab_id": "t2", "terminal_title_stripped": "Three"}]
    tabs = [{"tab_id": "t1", "label": "audit"}, {"tab_id": "t2", "label": "vscode"}]
    assert monitor.agent_names(agents, tabs) == {"a": "audit · One", "b": "audit · Two", "c": "vscode"}


def test_waiting_line_uses_the_sidebar_name():
    agents = [{"pane_id": "a", "workspace_id": "w1", "agent_status": "blocked", "terminal_title_stripped": "Long title"}]
    assert monitor.space_tokens(agents, {"a": {"name": "audit"}})["w1"]["wait1"] == "‼ audit"


def test_tabbar_line_shows_the_focused_agent(monkeypatch):
    monkeypatch.setattr(monitor, "cached_quotas", lambda account, now: [])  # not this machine's cache
    agents = [{"pane_id": "a", "focused": False, "tokens": {"context": "5h 10%"}},
              {"pane_id": "b", "focused": True, "tokens": {"context": "5h 100% · 41% (407k)"}}]
    accounts = {"a": ("pro", "sonnet-5.5"), "b": ("perso", "opus-5.5")}
    assert monitor.tabbar_line(agents, accounts) == "perso  opus-5.5  5h 100% · 41% (407k)"
    assert monitor.tabbar_line([{"pane_id": "a"}], accounts) == ""
    assert monitor.tabbar_line([{"pane_id": "x", "focused": True, "tokens": {"context": "\x1b[2Jc"}}], {}) == "[2Jc"
    windows = {"limit_5h_high": "88% 2h", "limit_7d_mid": "48% 5d", "context_meter": "⛁ 43% (432k)", "context": "x"}
    assert monitor.tabbar_line([{"pane_id": "b", "focused": True, "tokens": windows}], accounts) == \
        "perso  opus-5.5  5h 88% ↻2h · 7j 48% ↻5j  ⛁ 43% (432k)"
    assert monitor.quota_parts({"limit_7d_low": "9%"}) == ["7j 9%"]  # no reset reported


def test_cached_quotas_give_percent_used_and_exact_time_to_reset(tmp_path):
    now = 1_800_000_000
    cache = tmp_path / ".claude-perso" / monitor.LIMITS_CACHE
    cache.parent.mkdir(parents=True)
    cache.write_text(json.dumps({"fiveHour": {"usedPercentage": 12.4, "resetsAt": now + 3 * 3600 + 300},
                                 "sevenDay": {"usedPercentage": 72, "resetsAt": now + 4 * 86400 + 14 * 3600},
                                 "fetchedAtMs": now * 1000}))
    assert monitor.cached_quotas("perso", now, home=str(tmp_path)) == ["5h 12% ↻3h05", "7j 72% ↻4j14h"]
    assert monitor.cached_quotas("perso", now + 4 * 3600, home=str(tmp_path))[0] == "7j 72% ↻4j10h"  # 5h reset
    assert monitor.cached_quotas("pro", now, home=str(tmp_path)) == []


def test_write_tabbar_replaces_the_file(tmp_path):
    path = tmp_path / "s" / "tabbar"
    monitor.write_tabbar("perso  opus-5.5", str(path))
    assert path.read_text() == "perso  opus-5.5\n"
    monitor.write_tabbar("", str(path))
    assert path.read_text() == ""


def test_spaces_with_only_idle_agents_are_dimmed(monkeypatch):
    spaces = []
    agents = [{"pane_id": "p1", "workspace_id": "w1", "agent_status": "idle", "agent": "x"},
              {"pane_id": "p2", "workspace_id": "w2", "agent_status": "done", "agent": "x"}]
    workspaces = [{"workspace_id": "w1", "label": "chrysa"}, {"workspace_id": "w2", "label": "padam-av"}]
    replies = {("agent", "list"): {"result": {"agents": agents}},
               ("workspace", "list"): {"result": {"workspaces": workspaces}}}
    monkeypatch.setattr(monitor, "herdr", lambda *args: replies.get(args[:2], {}))
    monkeypatch.setattr(monitor, "agent_info", lambda agent: (None, "perso"))
    monkeypatch.setattr(monitor, "publish", lambda pane, tokens: None)
    monkeypatch.setattr(monitor, "publish_space", lambda ws, tokens: spaces.append((ws, tokens)))
    monitor.tick({"_refreshed": 10 ** 12})
    named = {ws: {k: v for k, v in t.items() if k.startswith("space_") and v} for ws, t in spaces}
    assert named == {"w1": {"space_idle_perso": "chrysa"}, "w2": {"space_icon": "✓", "space_busy_perso": "padam-av"}}


def test_a_child_space_shows_its_icon_after_its_name(monkeypatch):
    spaces = {}
    agents = [{"pane_id": "p1", "workspace_id": "w1", "agent_status": "working", "agent": "x"},
              {"pane_id": "p2", "workspace_id": "w2", "agent_status": "blocked", "agent": "x"}]
    workspaces = [{"workspace_id": "w1", "label": "padam-av"}, {"workspace_id": "w2", "label": "padam-av-GHA"}]
    replies = {("agent", "list"): {"result": {"agents": agents}},
               ("workspace", "list"): {"result": {"workspaces": workspaces}}}
    monkeypatch.setattr(monitor, "herdr", lambda *args: replies.get(args[:2], {}))
    monkeypatch.setattr(monitor, "agent_info", lambda agent: (None, "pro"))
    monkeypatch.setattr(monitor, "publish", lambda pane, tokens: None)
    monkeypatch.setattr(monitor, "publish_space", lambda ws, tokens: spaces.update({ws: tokens}))
    monitor.tick({"_refreshed": 10 ** 12})
    assert (spaces["w1"]["space_icon"], spaces["w1"][monitor.CHILD_ICON]) == ("◐", None)
    assert (spaces["w2"]["space_icon"], spaces["w2"][monitor.CHILD_ICON]) == (None, "‼")
    assert spaces["w2"]["space_busy_pro"] == "└ GHA"


def test_sub_tokens_summarize_for_an_agent_you_are_not_on():
    subs = [{"status": s, "description": f"S{i}"} for i, s in enumerate(["running", "running", "done"])]
    assert monitor.sub_tokens(subs, full=False) == {**dict.fromkeys(monitor.SUB_TOKENS), "sub1": "⑂ ●2 ✓1"}
    one = [{"status": "running", "description": "Only one"}]
    assert monitor.sub_tokens(one, full=False)["sub1"] == "⑂ ● Only one"  # one line either way
