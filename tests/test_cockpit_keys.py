"""Key bindings of the rendered herdr config: no collision, nothing silently shadowed.

`herdr config check` only reports a collision when both bindings are explicit. A custom
command on a key that herdr binds by default replaces that default without any warning,
so these tests compare the config with herdr's default prefix bindings.
"""

import os
import tomllib

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# herdr 0.9.3 default prefix bindings (https://herdr.dev/tui/docs/config-reference/).
HERDR_DEFAULTS = {
    "prefix+1..9": "switch_tab",
    "prefix+?": "help",
    "prefix+[": "copy_mode",
    "prefix+b": "toggle_sidebar",
    "prefix+c": "new_tab",
    "prefix+e": "edit_scrollback",
    "prefix+g": "goto",
    "prefix+h": "focus_pane_left",
    "prefix+j": "focus_pane_down",
    "prefix+k": "focus_pane_up",
    "prefix+l": "focus_pane_right",
    "prefix+minus": "split_horizontal",
    "prefix+n": "next_tab",
    "prefix+o": "open_notification_target",
    "prefix+p": "previous_tab",
    "prefix+q": "detach",
    "prefix+r": "resize_mode",
    "prefix+s": "settings",
    "prefix+shift+d": "close_workspace",
    "prefix+shift+g": "new_worktree",
    "prefix+shift+h": "swap_pane_left",
    "prefix+shift+j": "swap_pane_down",
    "prefix+shift+k": "swap_pane_up",
    "prefix+shift+l": "swap_pane_right",
    "prefix+shift+n": "new_workspace",
    "prefix+shift+p": "rename_pane",
    "prefix+shift+r": "reload_config",
    "prefix+shift+t": "rename_tab",
    "prefix+shift+tab": "cycle_pane_previous",
    "prefix+shift+w": "rename_workspace",
    "prefix+shift+x": "close_tab",
    "prefix+tab": "cycle_pane_next",
    "prefix+v": "split_vertical",
    "prefix+w": "workspace_picker",
    "prefix+x": "close_pane",
    "prefix+z": "zoom",
}


def load_keys():
    with open(os.path.join(ROOT, "tests", "fixtures", "config.toml"), "rb") as fh:
        keys = tomllib.load(fh)["keys"]
    builtins = {action: key for action, key in keys.items() if action not in ("command", "prefix")}
    commands = {c["key"]: c for c in keys["command"]}
    assert len(commands) == len(keys["command"]), "two custom commands share a key"
    return builtins, commands


def effective_bindings():
    """key -> list of what it triggers, defaults included unless rebound."""
    builtins, commands = load_keys()
    bound = {}
    for key, action in HERDR_DEFAULTS.items():
        if action not in builtins:
            bound.setdefault(key, []).append(action)
    for action, key in builtins.items():
        bound.setdefault(key, []).append(action)
    for key, command in commands.items():
        bound.setdefault(key, []).append(command["command"])
    return bound


def test_no_key_triggers_two_things():
    clashes = {key: what for key, what in effective_bindings().items() if len(what) > 1}
    assert clashes == {}


def test_custom_commands_stay_behind_the_prefix():
    _, commands = load_keys()
    assert [key for key in commands if not key.startswith("prefix+")] == []


def test_custom_commands_have_a_group_description():
    _, commands = load_keys()
    assert [key for key, c in commands.items() if ": " not in c.get("description", "")] == []
