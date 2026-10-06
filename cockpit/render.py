#!/usr/bin/env python3
"""Render cockpit templates from palette.toml.

Placeholders are {{section.key}} (e.g. {{colors.blue}}); the template syntax
stays out of herdr's own $token syntax. Unknown placeholders are an error.
"""
import os
import re
import sys
import tomllib

ROOT = os.path.dirname(os.path.abspath(__file__))
PLACEHOLDER = re.compile(r"\{\{\s*([a-z_]+)\.([a-z_]+)\s*\}\}")


def load_palette(path=os.path.join(ROOT, "palette.toml")):
    with open(path, "rb") as fh:
        return tomllib.load(fh)


def render(template, palette):
    def lookup(match):
        section, key = match.groups()
        try:
            return palette[section][key]
        except KeyError:
            raise KeyError(f"unknown placeholder {{{{{section}.{key}}}}}") from None
    return PLACEHOLDER.sub(lookup, template)


TEMPLATES_DIR = os.path.join(ROOT, "templates")


def templates():
    """Template names shipped with the plugin; the only names render_file accepts."""
    return sorted(entry.name for entry in os.scandir(TEMPLATES_DIR) if entry.is_file())


def render_file(name, palette=None):
    if name not in templates():
        raise ValueError(f"unknown template {name!r}; known: {', '.join(templates())}")
    with open(os.path.join(TEMPLATES_DIR, name)) as fh:
        return render(fh.read(), palette or load_palette())


if __name__ == "__main__":
    sys.stdout.write(render_file(sys.argv[1] if len(sys.argv) > 1 else "config.toml"))
