"""Shared pytest fixtures for Chronicle tests.

Three isolation styles:
- `tmp_home` — isolated HOME only (for tests that don't import codex_chronicle modules
  at the module level OR that monkeypatch module constants directly).
- `chronicle_env` — isolated HOME + reloads codex_chronicle.{config, storage, mode, ...}
  so their module-level `Path.home() / ".chronicle"` constants pick up the
  temp HOME. Use this when tests need to exercise the real marker layer.
- `isolated_env` — builds an env dict suitable for subprocess-based functional
  tests (functional/ dir). PATH contains a fake `codex` stub.

All three use a per-test temp directory and never touch the real
~/.chronicle or ~/.Codex.

Shared test helpers:
- `FakeDigest`, `FakeEntry` — minimal duck-typed replacements for
  SessionDigest / ChronicleEntry used across batch + storage tests.
- `seed_session` — factory to write a synthetic Codex JSONL.
"""
from __future__ import annotations

import importlib
import os
import shutil
import stat
import sys
import uuid
from dataclasses import dataclass, field
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parent.parent
FAKE_CODEX_SRC = Path(__file__).resolve().parent / "fixtures" / "fake_claude.py"


# ---------- Fake digest / entry (shared across batch + storage tests) ----------

@dataclass
class FakeDigest:
    """Minimal duck-typed replacement for codex_chronicle.extractor.SessionDigest."""
    session_id: str = ""
    project_slug: str = "-tmp-demo"
    start_time: str = "2026-04-17T00:00:00Z"
    end_time: str = "2026-04-17T00:01:00Z"
    total_turns: int = 1
    user_prompts: list = field(default_factory=list)
    project_path: str = "/tmp/demo"
    git_branch: str = "main"
    timeline: list = field(default_factory=list)
    tool_actions: list = field(default_factory=list)
    assistant_responses: list = field(default_factory=list)

    def __post_init__(self):
        if not self.session_id:
            self.session_id = str(uuid.uuid4())


@dataclass
class FakeEntry:
    """Minimal duck-typed replacement for codex_chronicle.summarizer.ChronicleEntry."""
    session_id: str = ""
    is_error: bool = False
    is_empty: bool = False
    error_kind: str = ""
    error_message: str = ""
    total_cost_usd: float = 0.0
    title: str = "Fake session"
    summary: str = "fake summary"
    narrative: str = ""
    decisions: list = field(default_factory=list)
    problems_solved: list = field(default_factory=list)
    human_reasoning: list = field(default_factory=list)
    follow_ups: list = field(default_factory=list)
    technical_details: dict = field(default_factory=dict)
    architecture: dict = field(default_factory=dict)
    planning: dict = field(default_factory=dict)
    open_questions: list = field(default_factory=list)
    files_changed: list = field(default_factory=list)
    cross_references: list = field(default_factory=list)
    # fields needed by session_filename():
    start_time: str = "2026-04-17T00:00:00Z"
    # fields needed by entry_to_session_markdown():
    project_path: str = "/tmp/demo"
    git_branch: str = "main"
    total_turns: int = 1
    user_prompts: list = field(default_factory=list)
    tool_actions: list = field(default_factory=list)
    turn_log: str = ""


def _install_fake_codex(bin_dir: Path) -> Path:
    """Install the fake codex binary in bin_dir and return its path."""
    bin_dir.mkdir(parents=True, exist_ok=True)
    target = bin_dir / "codex"
    target.write_text(FAKE_CODEX_SRC.read_text())
    target.chmod(target.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return target


# ---------- Fixtures ----------

# Modules whose path constants are computed at import from Path.home().
# Reloading them inside chronicle_env picks up the fake HOME.
_RELOADABLE_MODULES = (
    "codex_chronicle.config",
    "codex_chronicle.mode",
    "codex_chronicle.storage",
    "codex_chronicle.filtering",
    "codex_chronicle.locks",
    "codex_chronicle.service",
    "codex_chronicle.doctor",
    "codex_chronicle.daemon",
    "codex_chronicle.batch",
    "codex_chronicle.query",
    "codex_chronicle.hook",
)


def _reload_chronicle_modules(*names: str) -> None:
    """Reload chronicle submodules so module-level `Path.home()` constants
    re-resolve against the currently active HOME. Safe to call multiple times.
    """
    for name in names:
        if name in sys.modules:
            try:
                importlib.reload(sys.modules[name])
            except ModuleNotFoundError:
                pass
        else:
            importlib.import_module(name)


@pytest.fixture
def tmp_home(tmp_path, monkeypatch):
    """Per-test isolated HOME. Does NOT reload chronicle modules.
    Use for tests that either don't import codex_chronicle at module level, or
    that monkeypatch module constants directly.
    """
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(home / ".config"))
    for var in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL"):
        monkeypatch.delenv(var, raising=False)
    (home / ".codex" / "sessions").mkdir(parents=True, exist_ok=True)
    (home / ".codex-chronicle").mkdir(parents=True, exist_ok=True)
    yield home


@pytest.fixture
def chronicle_env(tmp_home):
    """Isolated HOME + reloaded chronicle modules.

    Returns a dict:
      home:              Path to the temp HOME
      chronicle_dir:     ~/.codex-chronicle inside the temp HOME
      codex_sessions:    ~/.codex/sessions inside the temp HOME
      reload(*modules):  re-run importlib.reload after setting a config key

    Use this for any test that calls into codex_chronicle.* functions whose
    behavior depends on filesystem paths under ~/.codex-chronicle or ~/.codex.
    """
    home = tmp_home
    _reload_chronicle_modules(*_RELOADABLE_MODULES)
    # Reset module-level caches that survive reload
    try:
        from codex_chronicle import codex_cli
        codex_cli._reset_cache_for_tests()
    except ImportError:
        pass
    try:
        from codex_chronicle import locks
        locks._reset_daemon_lock_for_tests()
    except ImportError:
        pass

    yield {
        "home": home,
        "chronicle_dir": home / ".codex-chronicle",
        "codex_sessions": home / ".codex" / "sessions",
        "reload": lambda *mods: _reload_chronicle_modules(*(mods or _RELOADABLE_MODULES)),
    }

    # After the test runs, cleanup caches so they don't leak into the next test
    try:
        from codex_chronicle import codex_cli
        codex_cli._reset_cache_for_tests()
    except ImportError:
        pass
    try:
        from codex_chronicle import locks
        locks._reset_daemon_lock_for_tests()
    except ImportError:
        pass


@pytest.fixture
def fake_codex_bin(tmp_path):
    """Path to a bin dir containing an executable `codex` stub.
    Does not set PATH — caller decides how to inject.
    """
    bin_dir = tmp_path / "bin"
    _install_fake_codex(bin_dir)
    return bin_dir


@pytest.fixture
def isolated_env(tmp_home, fake_codex_bin):
    """Env dict suitable for subprocess spawn in functional tests.

    PATH contains fake_codex_bin + minimal system dirs, mimicking the
    launchd minimal-env scenario but with a resolvable fake `codex`.
    """
    return {
        "HOME": str(tmp_home),
        "PATH": f"{fake_codex_bin}:/usr/bin:/bin:/usr/sbin:/sbin",
        "PYTHONPATH": str(REPO_ROOT),
        "FAKE_CLAUDE_MODE": "success",
        "LANG": "C.UTF-8",
    }


@pytest.fixture
def seed_session():
    """Factory to write a synthetic Codex session jsonl under a given
    `sessions_dir`. The shape mirrors real Codex rollouts closely enough
    for the extractor's `event_msg` / `response_item` paths to fire.

    Returns: seed_session(sessions_dir, slug, session_id=None, prompts=[...], cwd="...")
    """
    import json
    from datetime import datetime, timezone

    def _seed(sessions_dir: Path, slug: str, session_id: str | None = None,
              prompts: list[str] | None = None, cwd: str = "/tmp/fake") -> Path:
        session_id = session_id or str(uuid.uuid4())
        prompts = prompts or ["test prompt"]
        proj = sessions_dir / slug
        proj.mkdir(parents=True, exist_ok=True)
        jsonl = proj / f"{session_id}.jsonl"
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        lines = [json.dumps({
            "type": "session_meta",
            "timestamp": now,
            "payload": {"id": session_id, "cwd": cwd, "timestamp": now},
        })]
        for i, p in enumerate(prompts):
            lines.append(json.dumps({
                "type": "event_msg",
                "timestamp": now,
                "payload": {
                    "type": "user_message", "message": p, "turn_id": str(uuid.uuid4()),
                },
            }))
            lines.append(json.dumps({
                "type": "event_msg",
                "timestamp": now,
                "payload": {"type": "agent_message", "message": f"response {i}"},
            }))
        jsonl.write_text("\n".join(lines) + "\n")
        return jsonl

    return _seed
