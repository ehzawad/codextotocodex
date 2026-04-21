"""Read-only helpers for Codex session rollout files."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from .config import codex_sessions, project_slug_from_path


@dataclass(frozen=True)
class SessionMeta:
    session_id: str
    path: Path
    project_path: str
    project_slug: str
    start_time: str


def iter_session_files(root: Path | None = None) -> list[Path]:
    base = root or codex_sessions()
    if not base.exists():
        return []
    return sorted(p for p in base.rglob("*.jsonl") if "subagents" not in str(p))


def read_session_meta(path: Path) -> SessionMeta:
    session_id = path.stem
    project_path = ""
    start_time = ""

    try:
        with open(path, errors="ignore") as f:
            for line in f:
                if not line.strip():
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                timestamp = entry.get("timestamp") or ""
                if timestamp and not start_time:
                    start_time = timestamp
                payload = entry.get("payload")
                if not isinstance(payload, dict):
                    continue
                if entry.get("type") == "session_meta":
                    session_id = payload.get("id") or session_id
                    project_path = payload.get("cwd") or project_path
                    start_time = payload.get("timestamp") or start_time
                    break
                if entry.get("type") == "turn_context":
                    project_path = payload.get("cwd") or project_path
    except OSError:
        pass

    return SessionMeta(
        session_id=session_id,
        path=path,
        project_path=project_path,
        project_slug=project_slug_from_path(project_path),
        start_time=start_time,
    )
