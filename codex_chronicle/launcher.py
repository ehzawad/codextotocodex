"""Resolve runnable Codex Chronicle entrypoints.

These helpers answer a simple but important question: if the current process
successfully imported/ran Codex Chronicle, what command should we write into
hooks or service managers so future invocations work too?

We prefer an installed executable when one exists. When running from a source
checkout or editable install where no `codex-chronicle` binary is on PATH yet,
we fall back to the current interpreter with `-m codex_chronicle...`.
"""
from __future__ import annotations

import shlex
import shutil
import sys
from pathlib import Path


def _which(name: str) -> str | None:
    hit = shutil.which(name)
    if hit:
        return str(Path(hit).resolve())
    return None


def _user_bin(name: str) -> str | None:
    candidate = Path.home() / ".local" / "bin" / name
    if candidate.exists() and candidate.is_file():
        return str(candidate.resolve())
    return None


def resolve_cli_invocation(*extra_args: str) -> list[str]:
    """Return argv that can invoke Codex Chronicle from this environment."""
    if getattr(sys, "frozen", False):
        return [str(Path(sys.executable).resolve()), *extra_args]

    installed = _which("codex-chronicle") or _user_bin("codex-chronicle")
    if installed:
        return [installed, *extra_args]

    return [sys.executable, "-m", "codex_chronicle", *extra_args]


def resolve_hook_invocation() -> list[str]:
    """Return argv that can invoke the Chronicle hook from this environment."""
    installed = _which("codex-chronicle-hook") or _user_bin("codex-chronicle-hook")
    if installed:
        return [installed]

    if getattr(sys, "frozen", False):
        sibling = Path(sys.executable).resolve().with_name("codex-chronicle-hook")
        if sibling.exists():
            return [str(sibling)]

    return [sys.executable, "-m", "codex_chronicle.hook"]


def shell_join(argv: list[str]) -> str:
    """Render argv as a shell-safe command string."""
    return shlex.join(argv)
