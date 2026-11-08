# herdr-cockpit

<!-- Neutral agent instructions. Tool-specific files (e.g. CLAUDE.md) only import this one.
     HTML comments are stripped before loading: they cost no context. -->

## Overview

Herdr configuration (`cockpit`: templates, palette, `setup`/`status`/`validate`,
plugin manifest, native Agents-column filters) and one small plugin
(`agent-info`: account/model tokens, services pane). Prefer native herdr and
marketplace plugins; custom code only fills gaps. Plan and specs in `work/`.

## Commands

- `uv sync --locked` — install the dev environment (Python deps only in `pyproject.toml` + `uv.lock`).
- `uv run pytest` — run the test suite.
- `python3 cockpit/setup.py --dry-run` — show what setup would change; drop `--dry-run` to apply.
- `python3 cockpit/status.py` — drift report (exit 1 on drift).

## Conventions

- Everything written to disk is in English (identifiers, commits, docs).
- Configuration comes from environment variables; no committed secrets.
- No network, no telemetry: plugins read the herdr socket and local session files only.
- Text from agents or repos is stripped of control characters before it reaches a terminal.
- Colors and symbols come from `cockpit/palette.toml`, never hardcoded in templates.

## Boundaries

- Ask before any action with external effects (push, release, deploy, DNS, secrets, messages).
- Never add assistant attribution to commits, PRs, files or docs.
