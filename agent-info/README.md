# herdr-cockpit/agent-info

Herdr plugin that shows, on each agent row, the Claude account (`$account`) and the
LLM model (`$model`) the pane is running. Reads local Claude Code / Codex session
transcripts only; no network.

```toml
[ui.sidebar.agents]
rows = [
  [{ token = "$account", fg = "#f9e2af", bold = true }, { token = "$model", fg = "#cba6f7" }],
]
```

Install: `herdr plugin link <path-to-this-repo>`.
