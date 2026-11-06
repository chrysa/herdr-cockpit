import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "agent-info"))

import pytest


@pytest.fixture(autouse=True)
def _private_state(tmp_path, monkeypatch):
    """Keep the daemon's live files (tab bar line, marked tabs) out of test runs."""
    import monitor

    monkeypatch.setattr(monitor, "TABBAR", str(tmp_path / "tabbar"))
    monkeypatch.setattr(monitor, "MARKED", str(tmp_path / "marked-tabs.json"))
