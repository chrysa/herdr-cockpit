import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "cockpit"))

import daemon  # noqa: E402


def test_one_failing_renderer_does_not_stop_the_others():
    seen = []

    def boom(snap):
        raise RuntimeError("x")

    failed = daemon.run_tick({"agents": []}, [("a", boom), ("b", seen.append)])
    assert failed == ["a"]
    assert seen == [{"agents": []}]


def test_plugins_load_under_distinct_names():
    spaces = daemon.load("t_spaces", "spaces/monitor.py")
    agent_info = daemon.load("t_agent_info", "agent-info/monitor.py")
    assert hasattr(spaces, "publish_round")
    assert hasattr(agent_info, "tick")
    assert spaces is not agent_info


def test_spaces_gather_uses_the_given_snapshot():
    spaces = daemon.load("t_spaces2", "spaces/monitor.py")
    snap = {"panes": [], "workspaces": [{"workspace_id": "w1", "label": "padam-av"}],
            "agents": [{"workspace_id": "w1", "pane_id": "w1:p1", "agent_status": "blocked",
                        "tokens": {"account": "pro"}}]}
    found, pane_slot = spaces.gather({}, snap)
    assert found["w1"]["agents"] == 1
    assert found["w1"]["attention"]["blocked"] == 1
    assert "w1:p1" in pane_slot
