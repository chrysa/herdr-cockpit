"""Claude Code subagents of a session and their state, from Claude's own files.

<project>/<session>/subagents/agent-<id>.jsonl is each subagent's transcript and
agent-<id>.meta.json its description and spawning tool call. In the main transcript
<project>/<session>.jsonl, a <task-notification> carrying <task-id> and <status>
marks each stop, and a tool_result for the spawning call marks the end of a
foreground subagent. Same rules as the agent-panel plugin: a stop counts only if
nothing happened after it (a stopped subagent can be resumed); silent for
STALL_S = stalled. Only subagents active in the last WINDOW_S are listed.
"""

import json
import os
import re
from datetime import datetime

STALL_S = 5 * 60
WINDOW_S = 30 * 60
FIRST_READ = 2 * 1024 * 1024  # how far back the first read of a main transcript goes
GLYPHS = {"running": "●", "stalled": "◌", "failed": "✗", "killed": "⊘", "done": "✓"}
ORDER = tuple(GLYPHS)  # display order: what needs a look first
TASK_ID = re.compile(r"<task-id>([^<]+)</task-id>")
STATUS = re.compile(r"<status>([^<]+)</status>")
AGENT_FILE = re.compile(r"agent-(.+)\.jsonl")


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
        self.stops = {}  # subagent id -> (time, status)
        self.results = {}  # tool_use_id -> time

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
        horizon = now - 2 * WINDOW_S
        self.stops = {k: v for k, v in self.stops.items() if v[0] >= horizon}
        self.results = {k: v for k, v in self.results.items() if v >= horizon}

    def read_line(self, line, now):
        notification = "<task-notification>" in line
        if not notification and ('"tool_result"' not in line or "Async agent launched" in line):
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
            if isinstance(item, dict) and item.get("type") == "tool_result" and item.get("tool_use_id"):
                self.results[item["tool_use_id"]] = ts


def read_meta(path):
    try:
        with open(path) as fh:
            meta = json.load(fh)
        return meta if isinstance(meta, dict) else {}
    except (OSError, ValueError):
        return {}


def status_of(agent_id, tool_use_id, last, log, now):
    stop = log.stops.get(agent_id)
    if stop and stop[0] >= last - 2:
        return "done" if stop[1] == "completed" else stop[1]
    finished = log.results.get(tool_use_id) if tool_use_id else None
    if finished and finished >= last - 2:
        return "done"
    return "stalled" if now - last > STALL_S else "running"


def listing(main_path, log, now):
    """[{id, status, description, last}] of the session's subagents active in WINDOW_S."""
    folder = os.path.join(main_path.removesuffix(".jsonl"), "subagents")
    try:
        names = os.listdir(folder)
    except OSError:
        return []
    found = []
    for name in names:
        match = AGENT_FILE.fullmatch(name)
        if not match:
            continue
        try:
            last = os.path.getmtime(os.path.join(folder, name))
        except OSError:
            continue
        if now - last > WINDOW_S:
            continue
        agent_id = match.group(1)
        meta = read_meta(os.path.join(folder, f"agent-{agent_id}.meta.json"))
        found.append({
            "id": agent_id,
            "status": status_of(agent_id, meta.get("toolUseId"), last, log, now),
            "description": str(meta.get("description") or meta.get("agentType") or "agent"),
            "last": last,
        })
    return sorted(found, key=lambda s: (ORDER.index(s["status"]) if s["status"] in ORDER else len(ORDER), -s["last"]))
