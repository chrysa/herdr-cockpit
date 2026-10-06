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


def render_file(name, palette=None):
    with open(os.path.join(ROOT, "templates", name)) as fh:
        return render(fh.read(), palette or load_palette())


if __name__ == "__main__":
    sys.stdout.write(render_file(sys.argv[1] if len(sys.argv) > 1 else "config.toml"))
