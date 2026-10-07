#!/usr/bin/env python3
"""Validate the cockpit before it reaches a machine (`synapse validate` in spirit).

Checks, all offline:
1. palette.toml: every color is #RRGGBB, project slots and account colors exist;
2. every template renders with no placeholder left;
3. rendered JSON templates parse; the rendered herdr config parses as TOML;
4. the rendered herdr config passes `herdr config check` when herdr is installed
   (skipped, and said so, when it is not — e.g. in CI).

Exit code 0 when everything passes, 1 otherwise.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import tomllib

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import render  # noqa: E402

HEX = re.compile(r"^#[0-9a-fA-F]{6}$")


def check_palette(palette):
    errors = []
    for section in ("colors", "accounts"):
        for name, value in palette.get(section, {}).items():
            if isinstance(value, str) and not HEX.match(value):
                errors.append(f"palette [{section}].{name} = {value!r} is not #RRGGBB")
    slots = palette.get("colors", {}).get("slots", [])
    if len(slots) != 8:
        errors.append(f"palette colors.slots has {len(slots)} entries, expected 8")
    errors += [f"palette slot {s!r} is not a defined color" for s in slots if s not in palette["colors"]]
    errors += [f"palette [accounts] misses {a!r}" for a in ("perso", "pro", "codex", "other")
               if a not in palette.get("accounts", {})]
    return errors


def check_templates(palette):
    errors, rendered = [], {}
    for name in render.templates():
        try:
            text = render.render_file(name, palette)
        except KeyError as exc:
            errors.append(f"{name}: {exc}")
            continue
        if "{{" in text:
            errors.append(f"{name}: placeholder left after rendering")
        if name.endswith(".json"):
            try:
                json.loads(text)
            except ValueError as exc:
                errors.append(f"{name}: invalid JSON ({exc})")
        if name.endswith(".toml"):
            try:
                tomllib.loads(text)
            except tomllib.TOMLDecodeError as exc:
                errors.append(f"{name}: invalid TOML ({exc})")
        rendered[name] = text
    return errors, rendered


def check_herdr(config_text, herdr=None):
    """(errors, note) from `herdr config check` on the rendered config."""
    herdr = herdr or shutil.which("herdr")
    if not herdr:
        return [], "herdr not installed: `herdr config check` skipped"
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "config.toml")
        with open(path, "w") as fh:
            fh.write(config_text)
        out = subprocess.run([herdr, "config", "check"], capture_output=True, text=True,
                             env={**os.environ, "HERDR_CONFIG_PATH": path}, timeout=30)
    text = (out.stdout + out.stderr).strip()
    if out.returncode != 0 or "issues found" in text or "error" in text.lower():
        return [f"herdr config check: {text}"], ""
    return [], f"herdr config check: {text or 'ok'}"


def main():
    palette = render.load_palette()
    palette["paths"] = {"config": "/validate/config.toml", "bin": "/validate/bin"}
    errors = check_palette(palette)
    template_errors, rendered = check_templates(palette)
    errors += template_errors
    notes = []
    if "config.toml" in rendered:
        herdr_errors, note = check_herdr(rendered["config.toml"])
        errors += herdr_errors
        notes.append(note)
    for note in filter(None, notes):
        print(f"note  {note}")
    for error in errors:
        print(f"error {error}")
    print("ok: cockpit is valid" if not errors else f"{len(errors)} error(s)")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
