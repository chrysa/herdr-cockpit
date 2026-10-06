import info


def test_group_by_state_keeps_order_and_maps_unknown_to_idle():
    agents = [{"agent_status": s} for s in ("idle", "working", "blocked", "unknown", "done")]
    groups = info.group_by_state(agents)
    assert list(groups) == ["blocked", "working", "done", "idle"]
    assert len(groups["idle"]) == 2


def test_header_fills_width():
    plain = info.ANSI.sub("", info.header("Tâches", 30, "2/5"))
    assert plain.startswith("── Tâches ")
    assert plain.endswith(" 2/5")
    assert len(plain) == 29


def test_safe_strips_escape_sequences():
    assert info.safe("ok\x1b]0;pwn\x07\x1b[2J") == "ok]0;pwn"
