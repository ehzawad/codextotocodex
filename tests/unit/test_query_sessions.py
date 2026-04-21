"""Unit test for the bug where `chronicle query sessions` printed a
recovery command using the raw filesystem path instead of the Codex
project slug — making the suggested `chronicle process --project <path>`
find zero matches.
"""
from __future__ import annotations

import pytest


@pytest.fixture
def isolated_query(tmp_path, monkeypatch):
    fake_home = tmp_path / "home"
    (fake_home / ".codex-chronicle" / "projects").mkdir(parents=True)
    (fake_home / ".codex" / "sessions").mkdir(parents=True)
    monkeypatch.setenv("HOME", str(fake_home))

    import importlib
    for mod in ("codex_chronicle.config", "codex_chronicle.mode", "codex_chronicle.storage",
                "codex_chronicle.query", "codex_chronicle.daemon"):
        importlib.reload(__import__(mod, fromlist=["_"]))
    yield fake_home


def _seed_codex_jsonl(sessions_dir, session_id, cwd, project_path):
    """Write a synthetic Codex rollout with session_meta.payload.cwd set so
    read_session_meta computes the correct slug."""
    import json as j
    from datetime import datetime, timezone
    jsonl = sessions_dir / f"{session_id}.jsonl"
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    jsonl.write_text(j.dumps({
        "type": "session_meta",
        "timestamp": ts,
        "payload": {"id": session_id, "cwd": project_path, "timestamp": ts},
    }) + "\n")
    return jsonl


def test_suggested_command_uses_slug_not_raw_path(
    isolated_query, tmp_path, monkeypatch, capsys,
):
    """If the cwd has unprocessed JSONLs, the printed recovery command
    must use the slugged project name (substring-matches batch's filter),
    NOT the raw filesystem path (won't match because slashes vs dashes).
    """
    fake_home = isolated_query
    project_cwd = tmp_path / "my" / "project" / "foo"
    project_cwd.mkdir(parents=True)
    slug = str(project_cwd).replace("/", "-")
    sessions_dir = fake_home / ".codex" / "sessions" / "2026" / "04" / "21"
    sessions_dir.mkdir(parents=True)
    _seed_codex_jsonl(sessions_dir, "abc-123", str(project_cwd), str(project_cwd))

    monkeypatch.setattr("os.getcwd", lambda: str(project_cwd))

    from codex_chronicle import query
    query.sessions()
    captured = capsys.readouterr().out

    # Must print the slug, NOT the raw path, as the --project value
    assert f"--project {slug}" in captured
    for line in captured.splitlines():
        if "codex-chronicle process --project" in line:
            assert str(project_cwd) not in line, (
                f"raw path leaked into suggested command: {line!r}"
            )


def test_suggestion_is_substring_of_slug(isolated_query, tmp_path, monkeypatch, capsys):
    """batch.find_all_sessions substring-matches `--project` against
    slugged directory names. The suggested value must be a substring of
    at least one such directory; we assert by direct re-use.
    """
    fake_home = isolated_query
    project_cwd = tmp_path / "demo-proj"
    project_cwd.mkdir()
    slug = str(project_cwd).replace("/", "-")
    sessions_dir = fake_home / ".codex" / "sessions" / "2026" / "04" / "21"
    sessions_dir.mkdir(parents=True)
    _seed_codex_jsonl(sessions_dir, "sess-1", str(project_cwd), str(project_cwd))
    monkeypatch.setattr("os.getcwd", lambda: str(project_cwd))

    from codex_chronicle import query
    query.sessions()
    captured = capsys.readouterr().out
    for line in captured.splitlines():
        if "codex-chronicle process --project" in line:
            parts = line.strip().split()
            assert "--project" in parts
            idx = parts.index("--project")
            suggested = parts[idx + 1]
            # The suggestion must substring-match the actual slug (which is
            # how batch.find_all_sessions filters).
            assert suggested in slug, (
                f"suggested={suggested!r} not a substring of slug={slug!r}"
            )
            return
    pytest.fail("no `codex-chronicle process --project ...` line in output")
