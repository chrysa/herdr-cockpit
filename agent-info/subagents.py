"""Claude Code subagents of a session and their state, from Claude's own files.

<project>/<session>/subagents/agent-<id>.jsonl is each subagent's transcript and
agent-<id>.meta.json its description and spawning tool call. In the main transcript
<project>/<session>.jsonl, a <task-notification> carrying <task-id> and <status>
marks each stop, and a tool_result for the spawning call marks the end of a
foreground subagent. Same rules as the agent-panel plugin: a stop counts only if
nothing happened after it (a stopped subagent can be resumed); silent for
STALL_S = stalled. A finished subagent is listed for WINDOW_S after its last write;
one still running (no stop, no result, meta "finished" not true) for LONG_S, so a
long one stays visible while it works silently.
"""

import json
import os
import re
from datetime import datetime

# Also listed: workflow agents (<session>/subagents/workflows/<run>/agent-<id>.jsonl,
# finished once <session>/workflows/<run>.json reports a status other than running)
# and background tasks (a Bash call run or moved to the background: "running in
# background with ID: <id>" / "moved to the background (ID: <id>)" in its result,
# finished by its <task-notification>).

STALL_S = 5 * 60
WINDOW_S = 30 * 60
LONG_S = 6 * 3600  # how long an unfinished subagent or background task stays listed
FIRST_READ = 2 * 1024 * 1024  # how far back the first read of a main transcript goes
GLYPHS = {"running": "●", "stalled": "◌", "failed": "✗", "killed": "⊘", "done": "✓"}
ORDER = tuple(GLYPHS)  # display order: what needs a look first
TASK_ID = re.compile(r"<task-id>([^<]+)</task-id>")
STATUS = re.compile(r"<status>([^<]+)</status>")
AGENT_FILE = re.compile(r"agent-(.+)\.jsonl")
BACKGROUND_ID = re.compile(r"(?:running in background with ID: |moved to the background \(ID: )([A-Za-z0-9_-]+)")


def entry_time(entry, default):
    try:
        return datetime.fromisoformat(str(entry.get("timestamp"))).timestamp()
    except ValueError:
        return default


class MainLog:
    """Incremental reader of a main transcript: subagent stops and tool results."""

    def __init__(self, path):
        self.path = path
        self.offset = None
        self.partial = b""
        self.stops = {}  # subagent or task id -> (time, status)
        self.results = {}  # tool_use_id -> time
        self.calls = {}  # Bash tool_use_id -> (time, description)
        self.tasks = {}  # background task id -> (time started, description)

    def refresh(self, now):
        try:
            size = os.path.getsize(self.path)
            first = self.offset is None or size < self.offset  # new, or rewritten
            if first:
                self.offset, self.partial = max(0, size - FIRST_READ), b""
            with open(self.path, "rb") as fh:
                fh.seek(self.offset)
                data = fh.read()
                self.offset = fh.tell()
        except OSError:
            return
        lines = (self.partial + data).split(b"\n")
        self.partial = lines.pop()  # last line, possibly still being written
        if first and self.offset - len(data) > 0 and lines:
            lines = lines[1:]  # read from the middle of a line
        for raw in lines:
            self.read_line(raw.decode("utf-8", "replace"), now)
        # LONG_S, not WINDOW_S: a long subagent or task must keep its stop or start.
        horizon = now - LONG_S
        self.tasks = {k: v for k, v in self.tasks.items() if (self.stops.get(k) or v)[0] >= horizon}
        self.stops = {k: v for k, v in self.stops.items() if v[0] >= horizon}
        self.results = {k: v for k, v in self.results.items() if v >= horizon}
        self.calls = {k: v for k, v in self.calls.items() if v[0] >= horizon}

    def read_line(self, line, now):
        notification = "<task-notification>" in line
        call = '"tool_use"' in line and '"Bash"' in line
        if not (notification or call) and ('"tool_result"' not in line or "Async agent launched" in line):
            return
        try:
            entry = json.loads(line)
        except ValueError:
            return
        if not isinstance(entry, dict):
            return
        ts = entry_time(entry, now)
        message = entry.get("message") if isinstance(entry.get("message"), dict) else {}
        if notification:
            text = json.dumps(message.get("content") or entry.get("content")
                              or (entry.get("attachment") or {}).get("prompt") or "")
            task, status = TASK_ID.search(text), STATUS.search(text)
            if task and status and (task.group(1) not in self.stops or self.stops[task.group(1)][0] <= ts):
                self.stops[task.group(1)] = (ts, status.group(1))
            return
        content = message.get("content")
        for item in content if isinstance(content, list) else []:
            if not isinstance(item, dict):
                continue
            if item.get("type") == "tool_use" and item.get("name") == "Bash" and item.get("id"):
                given = item.get("input") if isinstance(item.get("input"), dict) else {}
                described = str(given.get("description") or given.get("command") or "Bash")
                self.calls[item["id"]] = (ts, described[:80])
            elif item.get("type") == "tool_result" and item.get("tool_use_id"):
                self.results[item["tool_use_id"]] = ts
                task = BACKGROUND_ID.search(json.dumps(item.get("content")))
                if task and task.group(1) not in self.tasks:
                    self.tasks[task.group(1)] = (ts, self.calls.get(item["tool_use_id"], (ts, "Bash"))[1])


def read_meta(path):
    try:
        with open(path) as fh:
            meta = json.load(fh)
        return meta if isinstance(meta, dict) else {}
    except (OSError, ValueError):
        return {}


def status_of(agent_id, tool_use_id, last, log, now, finished=False):
    """finished: the meta file says so (Claude Code sets "finished": true at the end)."""
    stop = log.stops.get(agent_id)
    if stop and stop[0] >= last - 2:
        return "done" if stop[1] == "completed" else stop[1]
    result = log.results.get(tool_use_id) if tool_use_id else None
    if (result and result >= last - 2) or finished:
        return "done"
    return "stalled" if now - last > STALL_S else "running"


UNFINISHED = ("running", "stalled")


def agent_files(folder):
    """(path, agent id, workflow run id or None) of the agents under a subagents folder."""
    try:
        names = os.listdir(folder)
    except OSError:
        return []
    found = [(os.path.join(folder, n), m.group(1), None) for n in names if (m := AGENT_FILE.fullmatch(n))]
    runs = os.path.join(folder, "workflows")
    try:
        run_ids = os.listdir(runs)
    except OSError:
        run_ids = []
    for run in run_ids:
        try:
            names = os.listdir(os.path.join(runs, run))
        except OSError:
            continue
        found += [(os.path.join(runs, run, n), m.group(1), run) for n in names if (m := AGENT_FILE.fullmatch(n))]
    return found


def workflow_status(session_dir, run):
    """The run's final status ("done", "failed", "killed"), None while it runs."""
    status = str(read_meta(os.path.join(session_dir, "workflows", f"{run}.json")).get("status") or "")
    return None if status in ("", "running") else ("done" if status == "completed" else status)


def listing(main_path, log, now):
    """[{id, status, description, last}] of the session's subagents, workflow agents and
    background tasks: finished ones active in WINDOW_S, unfinished ones in LONG_S."""
    session_dir = main_path.removesuffix(".jsonl")
    found, finished = [], {}
    for path, agent_id, run in agent_files(os.path.join(session_dir, "subagents")):
        try:
            last = os.path.getmtime(path)
        except OSError:
            continue
        if now - last > LONG_S:
            continue
        meta = read_meta(path.removesuffix(".jsonl") + ".meta.json")
        if run is not None and run not in finished:
            finished[run] = workflow_status(session_dir, run)
        status = (run and finished[run]) or status_of(agent_id, meta.get("toolUseId"), last, log, now,
                                                      meta.get("finished") is True)
        if now - last > (LONG_S if status in UNFINISHED else WINDOW_S):
            continue
        found.append({
            "id": agent_id,
            "status": status,
            "description": str(meta.get("description") or meta.get("agentType") or "agent"),
            "last": last,
        })
    for task_id, (started, description) in log.tasks.items():
        stop = log.stops.get(task_id)
        last = stop[0] if stop else started
        if now - last > (WINDOW_S if stop else LONG_S):
            continue
        status = ("done" if stop[1] == "completed" else stop[1]) if stop else "running"
        found.append({"id": task_id, "status": status, "description": description, "last": last})
    return sorted(found, key=lambda s: (ORDER.index(s["status"]) if s["status"] in ORDER else len(ORDER), -s["last"]))
