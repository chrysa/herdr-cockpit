import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "cockpit"))

import agent_view  # noqa: E402


def test_no_filter_when_nothing_selected():
    assert agent_view.build_filter(dict(agent_view.DEFAULT)) is None


def test_single_filter_is_not_wrapped():
    assert agent_view.build_filter({"profile": "pro", "active": False, "space": False}) == {
        "op": "eq", "field": {"token": "account"}, "value": "pro"}


def test_filters_combine_with_all():
    query = agent_view.build_filter({"profile": "", "active": True, "space": True})
    assert query["op"] == "all"
    assert [f["field"] for f in query["filters"]] == ["status", "workspace_id"]


def test_label():
    assert agent_view.label({"profile": "perso", "active": True, "space": False}) == "perso · actifs"
    assert agent_view.label(dict(agent_view.DEFAULT)) == "tous profils"


def test_sort_only_view_keeps_every_agent():
    import types
    calls = []
    agent_view.call = lambda method, params: calls.append((method, params)) or {}
    agent_view.apply({"profile": "", "active": False, "space": False, "attention": True})
    method, params = calls[-1]
    assert method == "agent.view.set"
    assert params["filter"] == {"op": "exists", "field": "pane_id"}
    assert params["sort"][0] == {"field": "attention", "order": "desc"}
