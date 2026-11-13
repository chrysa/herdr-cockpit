import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "cockpit"))

import shells  # noqa: E402


def test_only_panes_without_agent_are_listed():
    panes = [{"pane_id": "p1", "workspace_id": "w1", "agent": "claude", "cwd": "/a"},
             {"pane_id": "p2", "workspace_id": "w1", "cwd": "/b", "terminal_title": "bash x.sh"}]
    rows = shells.shell_rows(panes, [{"workspace_id": "w1", "label": "chrysa"}])
    assert [r["pane_id"] for r in rows] == ["p2"]
    assert rows[0]["space"] == "chrysa" and rows[0]["title"] == "bash x.sh"


def test_control_characters_are_stripped():
    panes = [{"pane_id": "p", "workspace_id": "w", "cwd": "/x\x1b[31m", "terminal_title": "t\x07"}]
    row = shells.shell_rows(panes, [{"workspace_id": "w", "label": "s\x1b"}])[0]
    assert row["cwd"] == "/x[31m" and row["title"] == "t" and row["space"] == "s"
