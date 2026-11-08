import json
import os
import socket
import threading

import events


def serve(path, lines, ready):
    server = socket.socket(socket.AF_UNIX)
    server.bind(path)
    server.listen(1)
    ready.set()
    conn, _ = server.accept()
    request = json.loads(conn.makefile().readline())
    conn.sendall(("\n".join(json.dumps(x) for x in lines(request)) + "\n").encode())
    threading.Event().wait(1)
    conn.close()
    server.close()


def start(tmp_path, lines):
    path = str(tmp_path / "herdr.sock")
    ready = threading.Event()
    threading.Thread(target=serve, args=(path, lines, ready), daemon=True).start()
    ready.wait(2)
    return path


def test_stream_subscribes_per_agent_pane_and_reports_events(tmp_path):
    seen = {}

    def lines(request):
        seen.update(request)
        return [{"id": request["id"], "result": {"type": "subscription_started"}},
                {"event": "tab_renamed", "data": {"tab_id": "t1"}}]

    stream = events.EventStream(start(tmp_path, lines))
    stream.follow(["w1:p2", "w1:p1"])
    assert stream.wait(2) is True
    assert seen["method"] == "events.subscribe"
    subs = seen["params"]["subscriptions"]
    assert {"type": "pane.agent_status_changed", "pane_id": "w1:p1"} in subs
    assert {"type": "tab.renamed"} in subs
    assert {"type": "workspace.metadata_updated"} not in subs  # fired by our own publishing


def test_refused_subscription_falls_back_to_sleeping(tmp_path):
    stream = events.EventStream(start(tmp_path, lambda request: [{"id": request["id"], "error": {"code": "x"}}]))
    stream.follow(["w1:p1"])
    assert stream.wait(2) is False
    assert stream.sock is None
    assert stream.wait(0.01) is False


def test_no_herdr_means_no_stream(tmp_path):
    stream = events.EventStream(str(tmp_path / "missing.sock"))
    stream.follow(["w1:p1"])
    assert stream.sock is None
    assert stream.wait(0.01) is False


def test_follow_reconnects_only_when_panes_change(tmp_path, monkeypatch):
    stream = events.EventStream(str(tmp_path / "x.sock"))
    connects = []
    monkeypatch.setattr(stream, "close", lambda: connects.append("close"))
    stream.sock, stream.panes = object(), {"w1:p1"}
    stream.follow(["w1:p1"])
    assert connects == []


def test_file_signature_changes_on_write(tmp_path):
    path = tmp_path / "s.jsonl"
    path.write_text("a\n")
    before = events.file_signature([str(path), str(tmp_path / "missing")])
    os.utime(path, ns=(1, 10 ** 18))
    assert events.file_signature([str(path), str(tmp_path / "missing")]) != before
