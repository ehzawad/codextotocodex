"""Emit Codex Chronicle context without Codex lifecycle hooks.

This is the explicit, no-hook replacement for the SessionStart hook's
automatic additionalContext payload. It reads generated Chronicle markdown
for the current project and prints concise context that Codex can consume
when the user asks for Chronicle memory. By default it does not truncate
Chronicle output; any cap must be requested explicitly.
"""
from __future__ import annotations

import argparse
import os

from .config import (
    load_recent_titles,
    project_chronicle_dir,
    project_slug_from_path,
)
from .query import _format_option, _pending_source_sessions


def _read_text(path, max_bytes: int = 0) -> str:
    try:
        text = path.read_text(errors="ignore")
    except OSError:
        return ""
    if max_bytes <= 0 or len(text.encode("utf-8")) <= max_bytes:
        return text.strip()
    encoded = text.encode("utf-8")[:max_bytes]
    return encoded.decode("utf-8", errors="ignore").rstrip() + "\n\n[truncated]"


def build_context(
    project_path: str | None = None,
    *,
    limit: int = 0,
    include_chronicle: bool = False,
    max_bytes: int = 0,
) -> str:
    cwd = (project_path or os.environ.get("CHRONICLE_ORIGINAL_CWD") or os.getcwd()).rstrip("/")
    slug = project_slug_from_path(cwd)
    project_dir = project_chronicle_dir(slug)
    title_limit = None if limit <= 0 else limit
    titles = load_recent_titles(slug, max_entries=title_limit)
    lines: list[str] = []

    if titles:
        lines.append("Previous sessions in this project (from Codex Chronicle):")
        lines.extend(f"- {title}" for title in titles)
        lines.append("")
        lines.append(
            "These are chronicled decisions from past sessions. Reference them only "
            "when they are relevant to the current work."
        )

    chronicle_file = project_dir / "chronicle.md"
    if include_chronicle and chronicle_file.exists():
        body = _read_text(chronicle_file, max_bytes)
        if body:
            if lines:
                lines.append("")
            lines.append("Project chronicle:")
            lines.append(body)

    if lines:
        return "\n".join(lines).rstrip() + "\n"

    pending = _pending_source_sessions(slug)
    if pending:
        process_filter = pending[0].project_slug
        return (
            f"No processed Codex Chronicle context for {cwd} yet.\n"
            f"{len(pending)} unprocessed Codex session(s) exist for this project.\n"
            "To generate Chronicle context now, run:\n"
            f"  codex-chronicle process {_format_option('--project', process_filter)} --workers 5\n"
        )

    return f"No Codex Chronicle context found for {cwd}.\n"


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Print no-hook Codex Chronicle context for a project.",
    )
    parser.add_argument("path", nargs="?", help="Project path. Defaults to current directory.")
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Recent session title limit. Default 0 means no limit.",
    )
    parser.add_argument(
        "--include-chronicle",
        action="store_true",
        help="Include the aggregate chronicle.md text when available.",
    )
    parser.add_argument(
        "--max-bytes",
        type=int,
        default=0,
        help="Maximum aggregate chronicle bytes to print. Default 0 means no limit.",
    )
    args = parser.parse_args(argv)
    print(
        build_context(
            args.path,
            limit=max(args.limit, 0),
            include_chronicle=args.include_chronicle,
            max_bytes=args.max_bytes,
        ),
        end="",
    )


if __name__ == "__main__":
    main()
