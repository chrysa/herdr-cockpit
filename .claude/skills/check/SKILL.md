---
name: check
description: Run this project's lint and test commands and report only what fails, with file and line. Use before committing or when asked whether the change is done.
allowed-tools: Bash(uv run ruff check . *) Bash(uv run pytest -q *)
---

Run, in order, stopping at the first failing step:

1. `uv run ruff check .`
2. `uv run pytest -q`

Report failures only: command, file:line, one-line cause. Do not fix anything unless asked.
If everything passes, say so in one line.
