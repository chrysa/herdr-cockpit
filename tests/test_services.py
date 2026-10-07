import json

import services


def ps_line(**kw):
    base = {"Names": "x", "State": "running", "Status": "Up 2 min", "HealthStatus": "healthy",
            "Ports": "", "Labels": "", "Mounts": ""}
    base.update(kw)
    return json.dumps(base)


def test_parse_ports_keeps_published_host_ports_once():
    assert services.parse_ports("0.0.0.0:8080->80/tcp, :::8080->80/tcp, 5432/tcp") == [8080]


def test_containers_match_compose_dir_or_mounts():
    out = "\n".join([
        ps_line(Names="api-1", Ports="0.0.0.0:8000->8000/tcp",
                Labels="com.docker.compose.project.working_dir=/p/app,com.docker.compose.service=api"),
        ps_line(Names="other", Labels="com.docker.compose.project.working_dir=/p/other"),
        ps_line(Names="mounted", State="exited", Mounts="/p/app/data"),
    ])
    found = services.containers("/p/app", ps_output=out)
    assert [c["name"] for c in found] == ["api", "mounted"]
    assert found[0]["urls"] == ["http://localhost:8000"]
    assert found[1]["state"] == "exited"


def test_listeners_keep_processes_running_inside_the_project():
    out = "\n".join([
        'LISTEN 0 511 0.0.0.0:5173 0.0.0.0:* users:(("node",pid=11,fd=20))',
        'LISTEN 0 10 127.0.0.1:36741 0.0.0.0:* users:(("brave",pid=22,fd=81))',
        'LISTEN 0 511 [::]:5173 [::]:* users:(("node",pid=11,fd=21))',
    ])
    cwds = {11: "/p/app/frontend", 22: "/home/u"}
    found = services.listeners("/p/app", ss_output=out, cwd_of=cwds.__getitem__)
    assert found == [{"name": "node", "pid": 11, "url": "http://localhost:5173"}]


def test_short_status():
    assert services.short_status("Up 3 hours (healthy)") == "up 3 h"
    assert services.short_status("Up About a minute") == "up 1 min"
    assert services.short_status("Up Less than a second") == "up 1 s"
    assert services.short_status("Exited (0) 3 minutes ago") == "exited 0"


def test_database_ports_have_no_scheme():
    assert services.address(5432) == "localhost:5432"
    assert services.address(8000) == "http://localhost:8000"
