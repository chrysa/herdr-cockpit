import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "agent-info"))
sys.path.insert(0, os.path.join(ROOT, "cockpit"))

import pytest


@pytest.fixture(autouse=True)
def _private_state(tmp_path, monkeypatch):
    """Keep live files out of test runs: the daemon's tab bar line, marked tabs,
    status line copies and closed-agent log, the Agents view state and server
    mark (CI has no state dir), and the socket requests that move spaces."""
    import agent_view
    import monitor

    monkeypatch.setattr(monitor, "TABBAR", str(tmp_path / "tabbar"))
    monkeypatch.setattr(monitor, "MARKED", str(tmp_path / "marked-tabs.json"))
    monkeypatch.setattr(monitor, "STATUSLINE_DIR", str(tmp_path / "statusline"))  # pruned on each tick
    monkeypatch.setattr(monitor, "CLOSED", str(tmp_path / "closed.jsonl"))
    view_dir = tmp_path / "chrysa.cockpit"
    monkeypatch.setattr(agent_view, "STATE_DIR", str(view_dir))
    monkeypatch.setattr(agent_view, "STATE", str(view_dir / "agent-view.json"))
    monkeypatch.setattr(agent_view, "SERVER_MARK", str(view_dir / "applied-server"))
    monkeypatch.setattr(monitor, "request", _no_socket)  # never move live spaces


def _no_socket(method, params):
    raise AssertionError(f"test reached the herdr socket: {method}")
