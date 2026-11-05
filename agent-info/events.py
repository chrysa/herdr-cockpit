"""Wake the agent-info daemon as soon as herdr or a Claude session changes.

herdr pushes events over its socket (`events.subscribe`): agent status, panes, tabs
and spaces created, closed, renamed or moved. A status subscription names one pane,
so the stream is reopened whenever the set of agent panes changes. Claude's last tool
call and subagents live in transcript files herdr knows nothing about: their mtimes
are checked every FILE_CHECK_S instead. workspace.metadata_updated is left out: the
daemon's own publishing fires it.
"""

import json
import os
import select
import socket

FILE_CHECK_S = 0.5
DEBOUNCE_S = 0.15  # a burst of events (an agent stopping renames its tab too) is one tick
GLOBAL_EVENTS = (
    "pane.created", "pane.closed", "pane.exited", "pane.updated", "pane.moved", "pane.agent_detected",
    "tab.created", "tab.closed", "tab.renamed", "tab.moved",
    "workspace.created", "workspace.closed", "workspace.renamed", "workspace.moved", "workspace.reordered",
)


def socket_path():
    return os.environ.get("HERDR_SOCKET_PATH") or os.path.expanduser("~/.config/herdr/herdr.sock")


def subscriptions(pane_ids):
    return [{"type": name} for name in GLOBAL_EVENTS] + [
        {"type": "pane.agent_status_changed", "pane_id": pane} for pane in sorted(pane_ids)]


class EventStream:
    """One subscription connection; without one (herdr restarting), waits just sleep."""

    def __init__(self, path=None):
        self.path = path or socket_path()
        self.sock = None
        self.panes = None
        self.buf = b""

    def follow(self, pane_ids):
        """Subscribe for these agent panes, reconnecting only when they changed."""
        pane_ids = set(pane_ids)
        if self.sock is not None and pane_ids == self.panes:
            return
        self.close()
        sock = socket.socket(socket.AF_UNIX)
        try:
            sock.settimeout(5)
            sock.connect(self.path)
            request = {"id": "agent-info-events", "method": "events.subscribe",
                       "params": {"subscriptions": subscriptions(pane_ids)}}
            sock.sendall((json.dumps(request) + "\n").encode())
            sock.setblocking(False)
        except OSError:
            sock.close()
            return
        self.sock, self.panes, self.buf = sock, pane_ids, b""

    def close(self):
        if self.sock is not None:
            self.sock.close()
        self.sock, self.panes, self.buf = None, None, b""

    def wait(self, timeout):
        """True when an event arrived within timeout; the backlog is drained."""
        if self.sock is None:
            select.select([], [], [], timeout)
            return False
        readable, _, _ = select.select([self.sock], [], [], timeout)
        if not readable:
            return False
        got = self.read()
        if got:
            select.select([], [], [], DEBOUNCE_S)
            self.read()
        return got

    def read(self):
        """Consume what is buffered; True if it held an event."""
        try:
            while True:
                chunk = self.sock.recv(65536)
                if not chunk:
                    self.close()  # herdr went away; follow() reconnects on the next tick
                    return False
                self.buf += chunk
        except BlockingIOError:
            pass
        except OSError:
            self.close()
            return False
        got = False
        *lines, self.buf = self.buf.split(b"\n")
        for line in lines:
            try:
                message = json.loads(line)
            except ValueError:
                continue
            if isinstance(message, dict) and message.get("error"):
                self.close()  # subscription refused: fall back to polling
                return got
            got = got or (isinstance(message, dict) and "event" in message)
        return got


def file_signature(paths):
    """Mtimes of the watched files and folders; changes when a session writes."""
    signature = []
    for path in sorted(paths):
        try:
            signature.append((path, os.stat(path).st_mtime_ns))
        except OSError:
            signature.append((path, None))
    return tuple(signature)
