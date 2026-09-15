# When to consult the IdeaGraph brain (opt-in snippet)

Paste into `CLAUDE.md` / `AGENTS.md` if you want the assistant to reach for
the brain proactively:

```markdown
## Knowledge brain
An IdeaGraph MCP server (tools: search_brain, get_node, neighbors,
brain_status) is available. Consult it BEFORE starting non-trivial design,
architecture or research work — it may already hold prior decisions,
constraints and related ideas. Skip it for routine edits, typo fixes and
mechanical refactors. `search_brain` scores are rank-fusion scores, not
similarities. The brain is read-only from here; changes go through the
owner (`ig ingest`, `ig pending`).
```

There is deliberately NO per-command hook: noisy PreToolUse nudges are the
known anti-pattern that gets MCP tools abandoned.
