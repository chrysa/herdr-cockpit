#!/usr/bin/env python3
"""Install the cockpit setup. Idempotent: a second run changes nothing.

Steps, each skipped when already in place:
1. render templates into the state dir;
2. link ~/.config/herdr/config.toml to the rendered config (backing up what
   was there);
3. point every Claude account's status line at the rendered script;
4. install the systemd user units and helper scripts;
5. enable the cockpit plugins, reload herdr.

`--dry-run` prints the plan without touching anything.
"""
import glob
import json
import os
import shutil
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import render  # noqa: E402

ROOT = os.path.dirname(os.path.abspath(__file__))
HOME = os.path.expanduser("~")
CONFIG = "config.toml"
PLUGINS = ("chrysa.spaces", "chrysa.agent-info")
UNITS = ("herdr-config-reload.path", "herdr-config-reload.service",
         "herdr-logrotate.service", "herdr-logrotate.timer")
ENABLE = ("herdr-config-reload.path", "herdr-logrotate.timer")


class Paths:
    def __init__(self, home=HOME):
        self.home = home
        self.state = os.path.join(home, ".local", "state", "chrysa.cockpit")
        self.rendered = os.path.join(self.state, "rendered")
        self.bin = os.path.join(self.state, "bin")
        self.herdr_config = os.path.join(home, ".config", "herdr", CONFIG)
        self.units = os.path.join(home, ".config", "systemd", "user")
        self.backups = os.path.join(self.state, "backups", time.strftime("%Y%m%d-%H%M%S"))

    def claude_dirs(self):
        return sorted({os.path.realpath(d) for d in glob.glob(os.path.join(self.home, ".claude-*"))
                       if os.path.isfile(os.path.join(d, "settings.json"))})


class Setup:
    def __init__(self, paths, dry_run=False, run=subprocess.run):
        self.p = paths
        self.dry_run = dry_run
        self.run = run
        self.changes = []

    def change(self, what):
        self.changes.append(what)
        return not self.dry_run

    def backup(self, path):
        if os.path.lexists(path):
            os.makedirs(self.p.backups, exist_ok=True)
            target = os.path.join(self.p.backups, path.lstrip("/").replace("/", "__"))
            if os.path.islink(path):
                with open(target + ".link", "w") as fh:
                    fh.write(os.readlink(path))
            else:
                shutil.copy2(path, target)

    def write(self, path, content, mode=0o644):
        try:
            with open(path) as fh:
                if fh.read() == content:
                    return
        except OSError:
            pass
        if self.change(f"write {path}"):
            os.makedirs(os.path.dirname(path), exist_ok=True)
            self.backup(path)
            tmp = path + ".tmp"
            with open(tmp, "w") as fh:
                fh.write(content)
            os.chmod(tmp, mode)
            os.replace(tmp, path)

    def link(self, path, target):
        if os.path.islink(path) and os.readlink(path) == target:
            return
        if self.change(f"link {path} -> {target}"):
            self.backup(path)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            if os.path.lexists(path):
                os.remove(path)
            os.symlink(target, path)

    def palette(self):
        palette = render.load_palette()
        palette["paths"] = {"config": os.path.join(self.p.rendered, CONFIG), "bin": self.p.bin}
        return palette

    def render_templates(self, palette):
        for name in render.templates():
            mode = 0o755 if name.endswith(".sh") else 0o644
            self.write(os.path.join(self.p.rendered, name), render.render_file(name, palette), mode)
        for name in sorted(os.listdir(os.path.join(ROOT, "bin"))):
            with open(os.path.join(ROOT, "bin", name)) as fh:
                self.write(os.path.join(self.p.bin, name), fh.read(), 0o755)

    def install_config(self):
        self.link(self.p.herdr_config, os.path.join(self.p.rendered, CONFIG))

    def install_statusline(self):
        script = os.path.join(self.p.rendered, "statusline.sh")
        for d in self.p.claude_dirs():
            path = os.path.join(d, "settings.json")
            with open(path) as fh:
                settings = json.load(fh)
            line = settings.get("statusLine") or {}
            if line.get("command") == script:
                continue
            if self.change(f"statusLine {os.path.basename(d)} -> {script}"):
                self.backup(path)
                settings["statusLine"] = {"type": "command", "command": script,
                                          "padding": line.get("padding", 0),
                                          "refreshInterval": line.get("refreshInterval", 10)}
                tmp = path + ".tmp"
                with open(tmp, "w") as fh:
                    json.dump(settings, fh, indent=2)
                    fh.write("\n")
                os.replace(tmp, path)

    def install_units(self, palette):
        before = len(self.changes)
        for name in UNITS:
            with open(os.path.join(ROOT, "units", name)) as fh:
                self.write(os.path.join(self.p.units, name), render.render(fh.read(), palette))
        if len(self.changes) > before and not self.dry_run:
            self.run(["systemctl", "--user", "daemon-reload"], check=False)
        for unit in ENABLE:
            active = self.run(["systemctl", "--user", "is-active", unit],
                              capture_output=True, text=True, check=False).stdout.strip() == "active"
            if not active and self.change(f"enable {unit}"):
                self.run(["systemctl", "--user", "enable", "--now", unit], check=False)

    def install_opencode_theme(self):
        """Link the rendered theme into opencode and select it in tui.json(c)."""
        config_dir = os.path.join(self.p.home, ".config", "opencode")
        if not os.path.isdir(config_dir):
            return
        self.link(os.path.join(config_dir, "themes", "chrysa-cockpit.json"),
                  os.path.join(self.p.rendered, "opencode-theme.json"))
        for name in ("tui.json", "tui.jsonc"):
            path = os.path.join(config_dir, name)
            if not os.path.exists(path):
                continue
            try:
                with open(path) as fh:
                    tui = json.load(fh)
            except ValueError:
                return  # comments or trailing commas: leave the user's file alone
            if tui.get("theme") != "chrysa-cockpit" and self.change(f"opencode theme in {path}"):
                self.backup(path)
                tui["theme"] = "chrysa-cockpit"
                with open(path, "w") as fh:
                    json.dump(tui, fh, indent=2)
                    fh.write("\n")
            return

    def enable_plugins(self):
        out = self.run(["herdr", "plugin", "list", "--json"], capture_output=True, text=True, check=False)
        data = json.loads(out.stdout or "{}")
        data = data.get("result", data)
        listing = data.get("plugins", data) if isinstance(data, dict) else data
        enabled = {p["plugin_id"] for p in listing if p.get("enabled")}
        for plugin in PLUGINS:
            if plugin not in enabled and self.change(f"enable plugin {plugin}"):
                self.run(["herdr", "plugin", "enable", plugin], check=False)

    def apply(self):
        palette = self.palette()
        self.render_templates(palette)
        self.install_config()
        self.install_statusline()
        self.install_units(palette)
        self.install_opencode_theme()
        self.enable_plugins()
        if self.changes and not self.dry_run:
            self.run(["herdr", "server", "reload-config"], check=False, capture_output=True)
        return self.changes


def main():
    dry_run = "--dry-run" in sys.argv
    changes = Setup(Paths(), dry_run=dry_run).apply()
    prefix = "would " if dry_run else ""
    for change in changes:
        print(prefix + change)
    if not changes:
        print("nothing to do: cockpit already in place")


if __name__ == "__main__":
    main()
