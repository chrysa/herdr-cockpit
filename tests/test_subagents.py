import json
import os

import subagents


def write_session(tmp_path, entries):
    main = tmp_path / "s1.jsonl"
    main.write_text("".join(json.dumps(e) + "\n" for e in entries))
    folder = tmp_path / "s1" / "subagents"
    folder.mkdir(parents=True)
    return main, folder


def add_subagent(folder, agent_id, mtime, **meta):
    (folder / f"agent-{agent_id}.jsonl").write_text("{}\n")
    (folder / f"agent-{agent_id}.meta.json").write_text(json.dumps(meta))
    os.utime(folder / f"agent-{agent_id}.jsonl", (mtime, mtime))


def notification(agent_id, status, ts):
    text = f"<task-notification><task-id>{agent_id}</task-id><status>{status}</status></task-notification>"
    return {"type": "user", "timestamp": ts, "message": {"content": text}}


def test_states_follow_agent_panel_rules(tmp_path):
    now = 1_800_000_000.0
    iso = lambda t: __import__("datetime").datetime.fromtimestamp(t, __import__("datetime").timezone.utc).isoformat()
    main, folder = write_session(tmp_path, [
        notification("done1", "completed", iso(now - 50)),
        notification("fail1", "failed", iso(now - 50)),
        notification("resumed", "completed", iso(now - 200)),  # stopped, then active again
        {"type": "user", "timestamp": iso(now - 40),
         "message": {"content": [{"type": "tool_result", "tool_use_id": "toolu_fg"}]}},
    ])
    add_subagent(folder, "done1", now - 60, description="Review")
    add_subagent(folder, "fail1", now - 60, description="Build")
    add_subagent(folder, "resumed", now - 10, description="Again")
    add_subagent(folder, "fg", now - 45, description="Foreground", toolUseId="toolu_fg")
    add_subagent(folder, "quiet", now - 400, agentType="Explore")
    add_subagent(folder, "long", now - 3 * 3600, description="Long")  # unfinished: kept LONG_S
    add_subagent(folder, "ended", now - 3 * 3600, description="Ended", finished=True)  # finished: WINDOW_S
    add_subagent(folder, "fork", now - 120, description="Fork", isFork=True, finished=True)
    add_subagent(folder, "ancient", now - 7 * 3600, description="Ancient")
    log = subagents.MainLog(str(main))
    log.refresh(now)
    found = {s["id"]: (s["status"], s["description"]) for s in subagents.listing(str(main), log, now)}
    assert found == {"done1": ("done", "Review"), "fail1": ("failed", "Build"), "resumed": ("running", "Again"),
                     "fg": ("done", "Foreground"), "quiet": ("stalled", "Explore"), "long": ("stalled", "Long"),
                     "fork": ("done", "Fork")}
    order = [s["id"] for s in subagents.listing(str(main), log, now)]
    assert order[:4] == ["resumed", "quiet", "long", "fail1"]


def test_main_log_reads_only_new_complete_lines(tmp_path):
    main = tmp_path / "s.jsonl"
    main.write_text(json.dumps(notification("a", "completed", "2026-11-05T21:00:00Z")) + "\n")
    log = subagents.MainLog(str(main))
    now = 1_793_900_000.0
    log.refresh(now)
    assert log.stops["a"][1] == "completed"
    with open(main, "a") as fh:
        fh.write(json.dumps(notification("b", "killed", "2026-11-05T21:01:00Z"))[:30])  # still being written
    log.refresh(now)
    assert "b" not in log.stops
    with open(main, "a") as fh:
        fh.write(json.dumps(notification("b", "killed", "2026-11-05T21:01:00Z"))[30:] + "\n")
    log.refresh(now)
    assert log.stops["b"][1] == "killed"


def test_missing_files_are_harmless(tmp_path):
    log = subagents.MainLog(str(tmp_path / "missing.jsonl"))
    log.refresh(0)
    assert subagents.listing(str(tmp_path / "missing.jsonl"), log, 0) == []


def iso_at(t):
    from datetime import UTC, datetime
    return datetime.fromtimestamp(t, UTC).isoformat()


def test_workflow_agents_follow_their_run(tmp_path):
    now = 1_800_000_000.0
    main, folder = write_session(tmp_path, [])
    for run, agent in (("wf_live", "a1"), ("wf_over", "a2")):
        (folder / "workflows" / run).mkdir(parents=True)
        add_subagent(folder / "workflows" / run, agent, now - 30, description=f"step {agent}")
    runs = tmp_path / "s1" / "workflows"
    runs.mkdir()
    (runs / "wf_over.json").write_text(json.dumps({"status": "completed"}))
    log = subagents.MainLog(str(main))
    log.refresh(now)
    found = {s["id"]: (s["status"], s["description"]) for s in subagents.listing(str(main), log, now)}
    assert found == {"a1": ("running", "step a1"), "a2": ("done", "step a2")}


def test_background_tasks_run_until_their_notification(tmp_path):
    now = 1_800_000_000.0
    call = lambda tid, description: {"type": "assistant", "timestamp": iso_at(now - 100), "message": {"content": [
        {"type": "tool_use", "id": tid, "name": "Bash", "input": {"command": "make test", "description": description}}]}}
    result = lambda tid, text: {"type": "user", "timestamp": iso_at(now - 99), "message": {"content": [
        {"type": "tool_result", "tool_use_id": tid, "content": text}]}}
    main, _ = write_session(tmp_path, [
        call("t1", "Run the suite"), result("t1", "Command running in background with ID: bg1. Output is being written"),
        call("t2", "Long build"), result("t2", [{"type": "text", "text": "Command did not complete within its 300s "
                                                  "timeout and was moved to the background (ID: bg2). Output"}]),
        call("t3", "Show a test"), result("t3", 'assert x == "Command running in background with ID: bg9."'),
        notification("bg2", "completed", iso_at(now - 20)),
    ])
    log = subagents.MainLog(str(main))
    log.refresh(now)
    found = {s["id"]: (s["status"], s["description"]) for s in subagents.listing(str(main), log, now)}
    assert found == {"bg1": ("running", "Run the suite"), "bg2": ("done", "Long build")}


def test_a_long_background_task_stays_listed_until_it_stops(tmp_path):
    now = 1_800_000_000.0
    started = now - 2 * 3600  # past WINDOW_S and the old 2 * WINDOW_S prune
    call = {"type": "assistant", "timestamp": iso_at(started - 1), "message": {"content": [
        {"type": "tool_use", "id": "t1", "name": "Bash", "input": {"command": "make all", "description": "Full build"}}]}}
    result = {"type": "user", "timestamp": iso_at(started), "message": {"content": [
        {"type": "tool_result", "tool_use_id": "t1", "content": "Command running in background with ID: bg1."}]}}
    main, _ = write_session(tmp_path, [call, result])
    log = subagents.MainLog(str(main))
    log.refresh(now)
    log.refresh(now + 60)  # later ticks must not prune it
    assert [(s["id"], s["status"]) for s in subagents.listing(str(main), log, now + 60)] == [("bg1", "running")]
    with open(main, "a") as fh:
        fh.write(json.dumps(notification("bg1", "completed", iso_at(now + 90))) + "\n")
    log.refresh(now + 100)
    assert [(s["id"], s["status"]) for s in subagents.listing(str(main), log, now + 100)] == [("bg1", "done")]
    log.refresh(now + 100 + subagents.WINDOW_S)
    assert subagents.listing(str(main), log, now + 100 + subagents.WINDOW_S) == []
