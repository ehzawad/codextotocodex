---
name: codex-chronicle
description: Load or search Codex Chronicle project memory without lifecycle hooks. Use when the user asks for Chronicle, prior Codex session history, project memory, past decisions, or "same context without hooks."
---

# Codex Chronicle

Use this skill only when the user explicitly asks for Chronicle memory or past
session context. Do not run Chronicle automatically on every turn.

## No-Hook Workflow

Use the bundled launcher so the skill works from this checkout even when the
global `codex-chronicle` command is not on `PATH`:

```bash
python3 ~/.agents/skills/codex-chronicle/scripts/chronicle.py context
```

If there are unprocessed sessions and the user wants fresh memory, run:

```bash
python3 ~/.agents/skills/codex-chronicle/scripts/chronicle.py process --workers 5
python3 ~/.agents/skills/codex-chronicle/scripts/chronicle.py context
```

For targeted lookup:

```bash
python3 ~/.agents/skills/codex-chronicle/scripts/chronicle.py query sessions
python3 ~/.agents/skills/codex-chronicle/scripts/chronicle.py query timeline --limit 20
python3 ~/.agents/skills/codex-chronicle/scripts/chronicle.py query search "term"
```

## Rules

- Treat hooks as opt-in experimental behavior. Do not suggest `install-hooks`
  unless the user specifically asks for automatic injection.
- `context` is cheap and reads generated markdown only. It has no output cap by
  default; `--limit` and `--max-bytes` are explicit opt-in caps.
- `process` spends model tokens through `codex exec`; run it only when the user
  asks to refresh or when stale/missing memory blocks the task. Chronicle does
  not truncate session transcripts or tool output by default, so the active
  model's context window is the real upper bound.
- When using Chronicle output, reconcile it with the live repo state before
  acting on it.
