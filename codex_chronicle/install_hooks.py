"""Configure Codex Chronicle hooks in Codex's hooks.json.

Codex discovers hooks from ~/.codex/hooks.json when
[features].codex_hooks = true is set in ~/.codex/config.toml.
"""
from __future__ import annotations

import json
import os
import re
import shlex
import sys
from pathlib import Path

from .launcher import resolve_hook_invocation, shell_join

HOOK_COMMAND = "codex-chronicle-hook"
LEGACY_RUNTIME_COMMAND = "codex-chronicle"


def resolved_hook_command() -> str:
    return shell_join(resolve_hook_invocation())


def chronicle_hooks() -> dict:
    command = resolved_hook_command()
    return {
        "SessionStart": [
            {
                "matcher": "startup|resume",
                "hooks": [
                    {
                        "type": "command",
                        "command": command,
                        "statusMessage": "Loading Codex Chronicle context...",
                        "timeout": 30,
                    }
                ],
            }
        ],
        "UserPromptSubmit": [
            {
                "hooks": [
                    {"type": "command", "command": command, "timeout": 30}
                ],
            }
        ],
        "Stop": [
            {
                "hooks": [
                    {"type": "command", "command": command, "timeout": 30}
                ],
            }
        ],
    }


def default_hooks_path() -> Path:
    return Path(os.environ.get("CODEX_HOME", Path.home() / ".codex")) / "hooks.json"


def default_config_path() -> Path:
    return Path(os.environ.get("CODEX_HOME", Path.home() / ".codex")) / "config.toml"


def _config_path_for_hooks_path(hooks_path: Path) -> Path:
    return hooks_path.parent / "config.toml"


def enable_codex_hooks(config_path: str | Path | None = None) -> None:
    path = Path(config_path) if config_path is not None else default_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    text = path.read_text() if path.exists() else ""

    if re.search(r"(?m)^\s*codex_hooks\s*=", text):
        text = re.sub(r"(?m)^(\s*codex_hooks\s*=\s*).*$", r"\1true", text)
    elif re.search(r"(?m)^\[features\]\s*$", text):
        text = re.sub(r"(?m)^(\[features\]\s*)$", r"\1\ncodex_hooks = true", text, count=1)
    else:
        if text and not text.endswith("\n"):
            text += "\n"
        text += "\n[features]\ncodex_hooks = true\n"

    path.write_text(text.lstrip("\n"))


def _without_chronicle_hook_entries(matcher_groups: list) -> list:
    kept_groups = []
    for mg in matcher_groups:
        if not isinstance(mg, dict):
            kept_groups.append(mg)
            continue
        entries = mg.get("hooks")
        if not isinstance(entries, list):
            kept_groups.append(mg)
            continue

        removed = False
        kept_entries = []
        for hook in entries:
            command = hook.get("command") if isinstance(hook, dict) else None
            if _is_chronicle_hook_command(command):
                removed = True
            else:
                kept_entries.append(hook)
        if not removed:
            kept_groups.append(mg)
        elif kept_entries:
            new_mg = dict(mg)
            new_mg["hooks"] = kept_entries
            kept_groups.append(new_mg)
    return kept_groups


def install_hooks(settings_path: str | None = None):
    path = Path(settings_path) if settings_path else default_hooks_path()

    if path.exists():
        try:
            raw = path.read_text()
            settings = json.loads(raw) if raw.strip() else {}
        except json.JSONDecodeError as e:
            print(
                f"ERROR: {path} is not valid JSON ({e}).\n"
                "Codex Chronicle will not overwrite it. Fix the file or back it up and retry.",
                file=sys.stderr,
            )
            sys.exit(2)
    else:
        settings = {}

    if not isinstance(settings, dict):
        print(f"ERROR: {path} top-level JSON is not an object.", file=sys.stderr)
        sys.exit(2)

    hooks = settings.get("hooks", {})
    if not isinstance(hooks, dict):
        hooks = {}

    for event_name in list(hooks.keys()):
        existing = hooks[event_name]
        if not isinstance(existing, list):
            continue
        stripped = _without_chronicle_hook_entries(existing)
        if stripped:
            hooks[event_name] = stripped
        else:
            del hooks[event_name]

    for event_name, chronicle_matchers in chronicle_hooks().items():
        existing = hooks.get(event_name, [])
        if not isinstance(existing, list):
            existing = []
        hooks[event_name] = existing + chronicle_matchers

    settings["hooks"] = hooks

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(settings, indent=2) + "\n")
    enable_codex_hooks(_config_path_for_hooks_path(path))
    print(f"Configured Codex Chronicle hooks in {path}")
    print(f"Enabled features.codex_hooks in {_config_path_for_hooks_path(path)}")


def _is_chronicle_hook_command(cmd) -> bool:
    if not isinstance(cmd, str) or not cmd.strip():
        return False
    try:
        parts = shlex.split(cmd)
    except ValueError:
        return False
    if not parts:
        return False
    first = os.path.basename(parts[0])
    if first in {HOOK_COMMAND, "chronicle-hook"}:
        return True
    if first == LEGACY_RUNTIME_COMMAND and _looks_like_runtime_binary(parts[0]):
        return True
    return len(parts) >= 3 and parts[1] == "-m" and parts[2] == "codex_chronicle.hook"


def _looks_like_runtime_binary(path: str) -> bool:
    normalized = path.replace("\\", "/")
    return "/.codex-chronicle/runtime/" in normalized


def uninstall_hooks(settings_path: str | None = None, dry_run: bool = False) -> int:
    p = Path(settings_path) if settings_path else default_hooks_path()
    if not p.exists():
        return 0

    try:
        raw = p.read_text()
        settings = json.loads(raw) if raw.strip() else {}
    except (OSError, json.JSONDecodeError) as e:
        print(f"WARN: {p} could not be read or parsed ({e}); leaving it alone.",
              file=sys.stderr)
        return 0

    if not isinstance(settings, dict):
        print(f"WARN: {p} top-level JSON is not an object; leaving it alone.",
              file=sys.stderr)
        return 0

    hooks = settings.get("hooks")
    if not isinstance(hooks, dict) or not hooks:
        return 0

    removed = 0
    for event_name in list(hooks.keys()):
        matcher_groups = hooks[event_name]
        if not isinstance(matcher_groups, list):
            continue
        kept_groups = []
        for mg in matcher_groups:
            if not isinstance(mg, dict):
                kept_groups.append(mg)
                continue
            entries = mg.get("hooks")
            if not isinstance(entries, list):
                kept_groups.append(mg)
                continue
            kept_entries = []
            for h in entries:
                cmd = (h or {}).get("command") if isinstance(h, dict) else None
                if _is_chronicle_hook_command(cmd):
                    removed += 1
                else:
                    kept_entries.append(h)
            if kept_entries:
                new_mg = dict(mg)
                new_mg["hooks"] = kept_entries
                kept_groups.append(new_mg)
        if kept_groups:
            hooks[event_name] = kept_groups
        else:
            del hooks[event_name]

    if not hooks:
        settings.pop("hooks", None)
    else:
        settings["hooks"] = hooks

    if removed and not dry_run:
        p.write_text(json.dumps(settings, indent=2) + "\n")

    return removed


if __name__ == "__main__":
    install_hooks(sys.argv[1] if len(sys.argv) >= 2 else None)
