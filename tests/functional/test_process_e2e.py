"""Functional tests for `chronicle process` end-to-end.

Exercises the full pipeline — session JSONL → codex exec subprocess → .md
and marker state — with a fake `codex` binary on PATH. No real LLM calls.

Each test runs `chronicle process --dry-run` or full `process` via
subprocess with a fully isolated HOME + PATH, so we can observe the same
behavior a user would see.
"""
from __future__ import annotations

import os
import stat
import subprocess
import sys
import uuid
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parent.parent.parent
FAKE_CODEX = Path(__file__).resolve().parent.parent / "fixtures" / "fake_claude.py"


def _install_fake_codex(bin_dir: Path) -> None:
    bin_dir.mkdir(parents=True, exist_ok=True)
    dst = bin_dir / "codex"
    dst.write_text(FAKE_CODEX.read_text())
    dst.chmod(dst.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)


def _seed_jsonl(codex_sessions: Path, slug: str, session_id: str) -> Path:
    """Seed a Codex rollout under ~/.codex/sessions/YYYY/MM/DD/.

    Uses the `session_meta` + `event_msg` shape the real Codex CLI emits —
    project identity comes from session_meta.payload.cwd, not a parent dir.
    """
    import json as j
    from datetime import datetime, timezone
    # Mirror the real Codex date-hierarchy layout so iter_session_files finds it.
    dated = codex_sessions / "2026" / "04" / "21"
    dated.mkdir(parents=True, exist_ok=True)
    jsonl = dated / f"{session_id}.jsonl"
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    # Recover a plausible cwd from the slug so project_slug_from_path agrees.
    cwd = "/" + slug.lstrip("-").replace("-", "/")
    lines = [
        j.dumps({
            "type": "session_meta",
            "timestamp": now,
            "payload": {"id": session_id, "cwd": cwd, "timestamp": now},
        }),
        j.dumps({
            "type": "event_msg",
            "timestamp": now,
            "payload": {
                "type": "user_message",
                "message": "please help with the refactor",
                "turn_id": session_id,
            },
        }),
        j.dumps({
            "type": "event_msg",
            "timestamp": now,
            "payload": {"type": "agent_message", "message": "on it"},
        }),
    ]
    jsonl.write_text("\n".join(lines) + "\n")
    return jsonl


def _run_chronicle(args: list[str], *, home: Path, bin_dir: Path,
                   fake_mode: str = "success") -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["HOME"] = str(home)
    env["PATH"] = f"{bin_dir}:/usr/bin:/bin:/usr/sbin:/sbin"
    env["FAKE_CLAUDE_MODE"] = fake_mode
    # PYTHONPATH lets the subprocess import the in-repo codex_chronicle
    # package even without a pip install -e; keeps the suite hermetic.
    env["PYTHONPATH"] = str(REPO_ROOT)
    # Invoke via the same interpreter running pytest so we hit the source
    # checkout rather than any globally installed codex-chronicle.
    cmd = [sys.executable, "-m", "codex_chronicle"] + args
    return subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=60)


@pytest.fixture
def fake_env(tmp_path):
    home = tmp_path / "home"
    (home / ".codex-chronicle").mkdir(parents=True)
    (home / ".codex" / "sessions").mkdir(parents=True)
    bin_dir = tmp_path / "bin"
    _install_fake_codex(bin_dir)
    return home, bin_dir


class TestForegroundHappyPath:
    def test_process_writes_session_md(self, fake_env):
        home, bin_dir = fake_env
        slug = "-tmp-demo"
        sid = str(uuid.uuid4())
        _seed_jsonl(home / ".codex" / "sessions", slug, sid)

        result = _run_chronicle(["process", "--workers", "2"],
                                home=home, bin_dir=bin_dir, fake_mode="success")
        assert result.returncode == 0, result.stderr + result.stdout

        # Session .md should exist under ~/.chronicle/projects/<slug>/sessions/
        sessions_dir = home / ".codex-chronicle" / "projects" / slug / "sessions"
        mds = list(sessions_dir.glob(f"*_{sid[:8]}*.md"))
        assert len(mds) == 1, f"expected 1 session md, got {mds}"
        content = mds[0].read_text()
        assert "Fake test session" in content  # title from fake Codex
        # Processed marker exists
        import hashlib
        h = hashlib.sha256(sid.encode()).hexdigest()[:16]
        assert (home / ".codex-chronicle" / ".processed" / h).exists()
        # No failure record
        assert not (home / ".codex-chronicle" / ".failed" / f"{h}.json").exists()


class TestInfraErrorDoesNotConsumeRetries:
    def test_missing_Codex_does_not_mark_terminal(self, fake_env):
        home, bin_dir = fake_env
        # Empty PATH → no Codex binary
        empty_bin = bin_dir.parent / "empty_bin"
        empty_bin.mkdir()
        slug = "-tmp-infra"
        sid = str(uuid.uuid4())
        _seed_jsonl(home / ".codex" / "sessions", slug, sid)

        # Run three times with no Codex on PATH — should NOT hit terminal
        for _ in range(3):
            _run_chronicle(["process", "--workers", "1"],
                           home=home, bin_dir=empty_bin, fake_mode="success")

        # Marker state: no success, no terminal failure
        import hashlib
        h = hashlib.sha256(sid.encode()).hexdigest()[:16]
        assert not (home / ".codex-chronicle" / ".processed" / h).exists()
        failed_path = home / ".codex-chronicle" / ".failed" / f"{h}.json"
        # Failure file may not exist at all (preferred) or if it does, must not be terminal
        if failed_path.exists():
            import json as j
            rec = j.loads(failed_path.read_text())
            assert not rec.get("terminal"), \
                "infra error must not promote to terminal; got terminal=true"


class TestTransientErrorGoesTerminalAfterMaxRetries:
    def test_fake_error_mode_reaches_terminal(self, fake_env):
        home, bin_dir = fake_env
        slug = "-tmp-transient"
        sid = str(uuid.uuid4())
        _seed_jsonl(home / ".codex" / "sessions", slug, sid)

        # Default max_retries is 3. Run `process` with fake_mode=error 3 times.
        for i in range(3):
            result = _run_chronicle(["process", "--workers", "1"],
                                    home=home, bin_dir=bin_dir, fake_mode="error")
            assert result.returncode == 0

        import hashlib
        import json as j
        h = hashlib.sha256(sid.encode()).hexdigest()[:16]
        failed_path = home / ".codex-chronicle" / ".failed" / f"{h}.json"
        assert failed_path.exists()
        rec = j.loads(failed_path.read_text())
        assert rec["terminal"] is True
        assert rec["attempts"] >= 3
        assert rec["last_error_kind"] in ("transient", "parse")


class TestRetryFailedRecovers:
    def test_retry_failed_after_fixing_cause(self, fake_env):
        home, bin_dir = fake_env
        slug = "-tmp-recover"
        sid = str(uuid.uuid4())
        _seed_jsonl(home / ".codex" / "sessions", slug, sid)

        # First: drive to terminal failure
        for _ in range(3):
            _run_chronicle(["process", "--workers", "1"],
                           home=home, bin_dir=bin_dir, fake_mode="error")

        import hashlib
        h = hashlib.sha256(sid.encode()).hexdigest()[:16]
        assert (home / ".codex-chronicle" / ".failed" / f"{h}.json").exists()

        # `process` without --retry-failed should skip it
        result = _run_chronicle(["process", "--workers", "1"],
                                home=home, bin_dir=bin_dir, fake_mode="success")
        assert result.returncode == 0
        assert "Terminal failures" in result.stdout or \
               "terminal" in result.stdout.lower()
        assert not (home / ".codex-chronicle" / ".processed" / h).exists()

        # --retry-failed + success mode → should succeed now
        result = _run_chronicle(["process", "--retry-failed", "--workers", "1"],
                                home=home, bin_dir=bin_dir, fake_mode="success")
        assert result.returncode == 0, result.stderr
        assert (home / ".codex-chronicle" / ".processed" / h).exists()
        assert not (home / ".codex-chronicle" / ".failed" / f"{h}.json").exists()


# Mode-switching round-trip (install-daemon/uninstall-daemon) is covered
# by the live verification in install.sh + `chronicle doctor` outputs, not
# in the subprocess-based functional suite, because exercising the real
# launchctl/systemctl here would either hit the actual user service
# manager or require heavyweight mocks for little additional insurance.
# Unit coverage for the mode switch itself lives in test_mode.py and
# test_service.py.
