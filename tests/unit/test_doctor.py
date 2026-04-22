"""Unit tests for codex_chronicle.doctor.

Verifies:
- collect_diagnostics returns a fully-serializable dict with stable keys
- `chronicle doctor --json` emits valid JSON with those keys
- `chronicle doctor` (text) still prints a readable report
- exit code semantics (0 if no drift, 1 if drift)
"""
from __future__ import annotations

import io
import json

import pytest


@pytest.fixture
def isolated_doctor(tmp_path, monkeypatch):
    fake_home = tmp_path / "home"
    (fake_home / ".codex-chronicle").mkdir(parents=True)
    (fake_home / ".codex" / "sessions").mkdir(parents=True)
    monkeypatch.setenv("HOME", str(fake_home))

    import importlib
    for mod in (
        "codex_chronicle.config", "codex_chronicle.mode", "codex_chronicle.service",
        "codex_chronicle.storage", "codex_chronicle.locks", "codex_chronicle.doctor",
    ):
        importlib.reload(__import__(mod, fromlist=["_"]))
    yield fake_home


_EXPECTED_TOP_KEYS = {
    "schema_version", "ok",
    "version", "chronicle_binary", "mode", "config_path",
    "codex", "daemon", "service", "locks", "sessions",
    "markers", "failed_sample", "drift_warnings",
}


def test_collect_diagnostics_has_expected_keys(isolated_doctor):
    from codex_chronicle import doctor
    data = doctor.collect_diagnostics()
    assert _EXPECTED_TOP_KEYS.issubset(data.keys()), \
        f"missing keys: {_EXPECTED_TOP_KEYS - data.keys()}"


def test_collect_diagnostics_is_serializable(isolated_doctor):
    from codex_chronicle import doctor
    data = doctor.collect_diagnostics()
    # Must round-trip through JSON without raising
    encoded = json.dumps(data, default=str)
    decoded = json.loads(encoded)
    assert decoded["mode"] == "foreground"


def test_run_json_mode_emits_valid_json(isolated_doctor, capsys):
    from codex_chronicle import doctor
    rc = doctor.run(["--json"])
    out = capsys.readouterr().out
    parsed = json.loads(out)  # raises on invalid JSON
    assert _EXPECTED_TOP_KEYS.issubset(parsed.keys())
    assert parsed["schema_version"] == 1
    assert isinstance(parsed["ok"], bool)
    # Isolated env may not have `codex` binary; just assert rc matches ok.
    assert (rc == 0) == parsed["ok"]


def test_run_text_mode_prints_human_report(isolated_doctor, capsys):
    from codex_chronicle import doctor
    rc = doctor.run([])  # no --json
    out = capsys.readouterr().out
    assert "codex-chronicle doctor" in out
    assert "mode:" in out
    assert "codex binary" in out
    assert "{" not in out  # not JSON
    # rc may be 0 or 1 depending on whether codex binary is resolvable
    # in the isolated test env; that's orthogonal to text-vs-json rendering.
    assert rc in (0, 1)


def test_collect_diagnostics_prefers_invoked_binary_over_path(
    isolated_doctor, monkeypatch, tmp_path,
):
    from codex_chronicle import doctor

    installed = tmp_path / "installed" / "codex-chronicle"
    installed.parent.mkdir(parents=True)
    installed.write_text("#!/bin/sh\n")

    other = tmp_path / "other-bin" / "codex-chronicle"
    other.parent.mkdir(parents=True)
    other.write_text("#!/bin/sh\n")

    monkeypatch.setattr(doctor.sys, "argv", [str(installed), "doctor", "--json"])
    monkeypatch.setenv("PATH", str(other.parent))

    data = doctor.collect_diagnostics()
    assert data["chronicle_binary"] == str(installed.absolute())


def test_run_exit_code_one_on_drift(isolated_doctor, monkeypatch, capsys):
    """Drift warning → exit code 1, in both text and JSON."""
    from codex_chronicle import doctor, mode, service
    mode.set_processing_mode("background")
    # Force drift: config says background but service file absent
    monkeypatch.setattr(service, "service_installed", lambda: False)
    monkeypatch.setattr(service, "service_running", lambda: False)
    rc_json = doctor.run(["--json"])
    _ = capsys.readouterr()
    rc_text = doctor.run([])
    _ = capsys.readouterr()
    assert rc_json == 1
    assert rc_text == 1


