# Codex Chronicle

Persistent, searchable engineering chronicles for Codex sessions.

Codex Chronicle reads Codex rollout JSONL files from:

```text
~/.codex/sessions/YYYY/MM/DD/rollout-*.jsonl
```

It writes its own state and generated markdown under:

```text
~/.codex-chronicle/
```

It never edits Codex's session rollouts. The only Codex files it can modify are
the hook/config files when you explicitly run `codex-chronicle install-hooks`.

## What It Captures

- User prompts and assistant responses from Codex rollout JSONL.
- Tool calls, shell command summaries, MCP calls, and tool outputs.
- Decisions, rejected approaches, debugging evidence, changed files, planning,
  follow-ups, and open questions.
- Per-session markdown plus a cumulative `chronicle.md` per project.

## Install

```bash
cd codextotocodex
python3 -m venv .venv
. .venv/bin/activate
pip install -e .
codex-chronicle doctor
```

The default workflow does not use Codex hooks. Run Chronicle explicitly when
you want memory:

```bash
codex-chronicle process --workers 5
codex-chronicle context
```

`context` prints the same kind of previous-session context the hook used to
inject, but only when you ask for it.

Hooks remain available as an experimental opt-in. To let Codex inject prior
session titles and log hook events automatically:

```bash
codex-chronicle install-hooks
```

That writes `~/.codex/hooks.json` and enables:

```toml
[features]
codex_hooks = true
```

in `~/.codex/config.toml`. Restart Codex after installing hooks.

For a user-style install (no clone required):

```bash
curl -fsSL https://raw.githubusercontent.com/ehzawad/codextotocodex/main/install.sh | bash
```

Or, from a checkout: `bash install.sh`. Either way, the script downloads the
prebuilt release for `linux-x86_64` or `darwin-arm64`, verifies its SHA256,
and atomically swaps it into `~/.codex-chronicle/runtime/`. If the download
fails, it falls back to a source-based install in a managed venv under
`~/.codex-chronicle/runtime/venv`.

Releases are built by `.github/workflows/release.yml` on each push to `main`;
the workflow keeps only the latest GitHub release and deletes older release
tags on each publish.

The installer does not enable hooks by default. To opt in during install:

```bash
CODEX_CHRONICLE_INSTALL_HOOKS=1 bash install.sh
```

Symlinks land at:

```text
~/.local/bin/codex-chronicle
~/.local/bin/codex-chronicle-hook
```

## Default Mode

Foreground mode is the default. Codex Chronicle does not spend model tokens
unless you run one of:

```bash
codex-chronicle process
codex-chronicle context --include-chronicle
codex-chronicle insight
codex-chronicle story
codex-chronicle rewind --summary N
```

Background mode is opt-in:

```bash
codex-chronicle install-daemon
codex-chronicle uninstall-daemon
```

## Common Commands

```bash
codex-chronicle doctor --json
codex-chronicle query projects
codex-chronicle query sessions
codex-chronicle query timeline --limit 20
codex-chronicle query search "auth"
codex-chronicle context

codex-chronicle process --dry-run
codex-chronicle process --workers 5
codex-chronicle process --project my-project --workers 5
codex-chronicle process --project=-Users-name-project --workers 5
codex-chronicle process --retry-failed --workers 5

codex-chronicle rewind
codex-chronicle insight my-project
codex-chronicle story my-project
codex-chronicle update
```

Notes:

- `--workers` must be `>= 1`.
- If a project filter starts with `-`, prefer the `--project=<value>` form.

## Codex-Specific Design

- Session discovery walks `~/.codex/sessions/` and reads project identity from
  each rollout's `session_meta.payload.cwd`.
- Hook install follows Codex's documented `hooks.json` and
  `[features].codex_hooks = true` configuration.
- Summarization uses `codex exec --ephemeral --json --output-schema` with
  `--sandbox read-only`, `approval_policy="never"`, and configurable
  `model_reasoning_effort`.
- Observer calls are prefixed with a Codex Chronicle sentinel and run with
  `CODEX_CHRONICLE_OBSERVER=1`; the scanner skips those sessions if a future
  Codex CLI ever persists them despite `--ephemeral`.
- State, locks, daemon files, and generated markdown are independent from the
  original Claude Chronicle project, so both tools can run on the same machine.

## Config

`~/.codex-chronicle/config.json` is created on first use:

```json
{
  "processing_mode": "foreground",
  "concurrency": 5,
  "model": "gpt-5.4",
  "reasoning_effort": "high",
  "poll_interval_seconds": 5,
  "quiet_minutes": 5,
  "scan_interval_minutes": 30,
  "max_retries": 3,
  "skip_projects": []
}
```

`codex-chronicle doctor` reports the resolved `codex` binary, Codex CLI
version, daemon/service state, lock state, marker counts, and unprocessed
session count.
