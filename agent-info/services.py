"""Web apps, processes and containers a project exposes, for the info panel.

Read-only and local: `docker ps` (containers whose compose working dir is the
project, or whose bind mounts sit inside it) and `ss -ltnp` (TCP listeners
whose process runs from inside the project). Results are cached a few seconds
because the panel redraws every second.
"""
import json
import os
import re
import subprocess
import threading
import time

CACHE_S = 5
DOCKER_REFRESH_S = 30  # `docker ps` can take ~20 s on a busy daemon: never on the draw path
_cache = {}
_docker = {"output": "", "started": False}


def _run(args, timeout=4):
    try:
        out = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError):
        return ""
    return out.stdout if out.returncode == 0 else ""


def _inside(path, root):
    path, root = os.path.normpath(path), os.path.normpath(root)
    return path == root or path.startswith(root + os.sep)


def parse_ports(ports):
    """"0.0.0.0:8080->80/tcp, :::8080->80/tcp" -> [8080] (published host ports, unique)."""
    found = []
    for part in ports.split(","):
        host = part.strip().split("->")[0]
        if "->" in part and host.rsplit(":", 1)[-1].isdigit():
            port = int(host.rsplit(":", 1)[-1])
            if port not in found:
                found.append(port)
    return found


# Ports that speak a database or broker protocol, not HTTP: shown without a scheme.
NON_HTTP = {1433, 1521, 2181, 3306, 5432, 5672, 6379, 9042, 9092, 11211, 11434, 27017}


def address(port, host="localhost"):
    return f"{host}:{port}" if port in NON_HTTP else f"http://{host}:{port}"


def short_status(status):
    """"Up 3 hours (healthy)" -> "up 3 h"; "Exited (0) 3 minutes ago" -> "exited 0"."""
    words = status.replace("(", " ").replace(")", " ").split()
    if not words:
        return ""
    if words[0] == "Up":
        units = {"seconds": "s", "second": "s", "minutes": "min", "minute": "min", "hours": "h",
                 "hour": "h", "days": "d", "day": "d", "weeks": "w", "week": "w"}
        rest = [w for w in words[1:] if w not in ("About", "Less", "than", "a", "an")]
        if not rest:
            return "up"
        if not rest[0].isdigit():
            rest = ["1"] + rest
        unit = units.get(rest[1], rest[1]) if len(rest) > 1 else ""
        return f"up {rest[0]} {unit}".strip()
    if words[0] == "Exited":
        return f"exited {words[1]}" if len(words) > 1 else "exited"
    return words[0].lower()


def parse_labels(labels):
    out = {}
    for item in labels.split(","):
        key, _, value = item.partition("=")
        out[key.strip()] = value.strip()
    return out


def _docker_loop():
    while True:
        _docker["output"] = _run(["docker", "ps", "-a", "--no-trunc", "--format", "{{json .}}"], timeout=60)
        time.sleep(DOCKER_REFRESH_S)


def docker_snapshot():
    """Latest `docker ps` output, refreshed by a background thread (empty until the first read)."""
    if not _docker["started"]:
        _docker["started"] = True
        threading.Thread(target=_docker_loop, daemon=True).start()
    return _docker["output"]


def containers(root, ps_output=None):
    """[{name, state, status, health, urls}] for containers belonging to root."""
    raw = docker_snapshot() if ps_output is None else ps_output
    found = []
    for line in raw.splitlines():
        try:
            c = json.loads(line)
        except ValueError:
            continue
        labels = parse_labels(c.get("Labels", ""))
        workdir = labels.get("com.docker.compose.project.working_dir", "")
        mounts = [m for m in c.get("Mounts", "").split(",") if m.startswith("/")]
        if not (workdir and _inside(workdir, root)) and not any(_inside(m, root) for m in mounts):
            continue
        found.append({
            "name": labels.get("com.docker.compose.service") or c.get("Names", "?"),
            "state": c.get("State", "?"),
            "health": c.get("HealthStatus", "none"),
            "urls": [address(p) for p in parse_ports(c.get("Ports", ""))],
            "status": short_status(c.get("Status", "")),
        })
    return found


SS_LINE = re.compile(r'\S+\s+\S+\s+\S+\s+(\S+):(\d+)\s+\S+\s+users:\(\("([^"]+)",pid=(\d+)')


def listeners(root, ss_output=None, cwd_of=None):
    """[{name, pid, url}] for TCP listeners whose process cwd is inside root."""
    raw = _run(["ss", "-ltnpH"]) if ss_output is None else ss_output
    cwd_of = cwd_of or (lambda pid: os.readlink(f"/proc/{pid}/cwd"))
    found, seen = [], set()
    for line in raw.splitlines():
        m = SS_LINE.search(line)
        if not m:
            continue
        addr, port, name, pid = m.group(1), int(m.group(2)), m.group(3), int(m.group(4))
        try:
            if not _inside(cwd_of(pid), root):
                continue
        except OSError:
            continue
        if port in seen:
            continue
        seen.add(port)
        host = "localhost" if addr in ("*", "0.0.0.0", "[::]", "127.0.0.1", "[::1]") else addr.strip("[]")
        found.append({"name": name, "pid": pid, "url": address(port, host)})
    return found


def services(root):
    """Cached (containers, listeners) for a project root."""
    hit = _cache.get(root)
    if hit and time.monotonic() - hit[0] < CACHE_S:
        return hit[1]
    value = (containers(root), listeners(root)) if root else ([], [])
    _cache[root] = (time.monotonic(), value)
    return value
