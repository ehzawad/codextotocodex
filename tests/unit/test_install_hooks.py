"""Unit tests for codex_chronicle.install_hooks.

Chronicle must NOT silently clobber a user's ~/.Codex/settings.json if
it's malformed — it should refuse with a clear error message so the
user can fix (or back up) the file themselves.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest


def test_creates_fresh_settings_when_absent(tmp_path):
    from codex_chronicle.install_hooks import install_hooks
    settings = tmp_path / "settings.json"
    install_hooks(str(settings))
    assert settings.exists()
    data = json.loads(settings.read_text())
    assert "hooks" in data
    assert "SessionStart" in data["hooks"]
    assert "codex_hooks = true" in (tmp_path / "config.toml").read_text()


def test_merges_into_existing_valid_settings(tmp_path):
    from codex_chronicle.install_hooks import install_hooks
    settings = tmp_path / "settings.json"
    settings.write_text(json.dumps({
        "theme": "dark",
        "hooks": {"MyEvent": [{"matcher": "", "hooks": []}]},
    }))
    install_hooks(str(settings))
    data = json.loads(settings.read_text())
    assert data["theme"] == "dark"  # user's key survives
    assert "MyEvent" in data["hooks"]  # user's hooks survive
    assert "SessionStart" in data["hooks"]  # chronicle hooks added


def test_malformed_json_refuses_with_exit_code(tmp_path, capsys):
    from codex_chronicle.install_hooks import install_hooks
    settings = tmp_path / "settings.json"
    settings.write_text("{ not json,}")  # invalid
    with pytest.raises(SystemExit) as excinfo:
        install_hooks(str(settings))
    assert excinfo.value.code == 2
    err = capsys.readouterr().err
    assert "not valid JSON" in err
    # File is left UNCHANGED — we don't clobber user state
    assert settings.read_text() == "{ not json,}"


def test_non_object_json_refuses(tmp_path, capsys):
    from codex_chronicle.install_hooks import install_hooks
    settings = tmp_path / "settings.json"
    settings.write_text('"just a string"')
    with pytest.raises(SystemExit) as excinfo:
        install_hooks(str(settings))
    assert excinfo.value.code == 2


def test_idempotent_reinstall_doesnt_duplicate_hooks(tmp_path):
    from codex_chronicle.install_hooks import install_hooks, _is_chronicle_hook_command
    settings = tmp_path / "settings.json"
    install_hooks(str(settings))
    install_hooks(str(settings))  # run again
    data = json.loads(settings.read_text())
    # SessionEnd is not one of the events we install — only the three in
    # CHRONICLE_HOOKS get entries, and Codex's hook vocabulary treats
    # SessionEnd as a synonym for Stop, which we already cover.
    for event in ("SessionStart", "Stop", "UserPromptSubmit"):
        # Each event should have exactly ONE codex-chronicle-hook matcher group
        groups = data["hooks"][event]
        chronicle_count = sum(
            1 for g in groups
            for h in g.get("hooks", [])
            if _is_chronicle_hook_command(h.get("command"))
        )
        assert chronicle_count == 1, f"{event}: expected 1 chronicle hook, got {chronicle_count}"


def test_uses_python_module_fallback_when_no_hook_binary_on_path(tmp_path, monkeypatch):
    from codex_chronicle.install_hooks import install_hooks
    settings = tmp_path / "settings.json"
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setenv("HOME", str(fake_home))
    monkeypatch.setenv("PATH", str(tmp_path / "empty"))
    install_hooks(str(settings))
    data = json.loads(settings.read_text())
    commands = [
        h["command"]
        for groups in data["hooks"].values()
        for group in groups
        for h in group.get("hooks", [])
    ]
    assert commands
    assert all("codex_chronicle.hook" in cmd for cmd in commands)


def test_preserves_hook_symlink_name_for_single_binary_install(tmp_path, monkeypatch):
    from codex_chronicle.install_hooks import install_hooks
    settings = tmp_path / "settings.json"
    bin_dir = tmp_path / "bin"
    runtime_dir = tmp_path / ".codex-chronicle" / "runtime"
    bin_dir.mkdir()
    runtime_dir.mkdir(parents=True)
    runtime_binary = runtime_dir / "codex-chronicle"
    runtime_binary.write_text("#!/bin/sh\n")
    runtime_binary.chmod(0o755)
    hook_link = bin_dir / "codex-chronicle-hook"
    hook_link.symlink_to(runtime_binary)
    monkeypatch.setenv("PATH", str(bin_dir))

    install_hooks(str(settings))

    data = json.loads(settings.read_text())
    commands = [
        h["command"]
        for groups in data["hooks"].values()
        for group in groups
        for h in group.get("hooks", [])
    ]
    assert commands
    assert all(cmd == str(hook_link) for cmd in commands)
    assert all("/runtime/codex-chronicle" not in cmd for cmd in commands)


def test_reinstall_removes_legacy_resolved_runtime_hook(tmp_path, monkeypatch):
    from codex_chronicle.install_hooks import install_hooks
    settings = tmp_path / "settings.json"
    bin_dir = tmp_path / "bin"
    runtime_dir = tmp_path / ".codex-chronicle" / "runtime"
    bin_dir.mkdir()
    runtime_dir.mkdir(parents=True)
    runtime_binary = runtime_dir / "codex-chronicle"
    runtime_binary.write_text("#!/bin/sh\n")
    runtime_binary.chmod(0o755)
    hook_link = bin_dir / "codex-chronicle-hook"
    hook_link.symlink_to(runtime_binary)
    monkeypatch.setenv("PATH", str(bin_dir))
    settings.write_text(json.dumps({
        "hooks": {
            "Stop": [{
                "hooks": [
                    {"type": "command", "command": str(runtime_binary), "timeout": 30},
                    {"type": "command", "command": "user-hook"},
                ],
            }],
        },
    }))

    install_hooks(str(settings))

    data = json.loads(settings.read_text())
    all_commands = [
        h["command"]
        for groups in data["hooks"].values()
        for group in groups
        for h in group.get("hooks", [])
    ]
    assert str(runtime_binary) not in all_commands
    assert "user-hook" in all_commands
    assert all_commands.count(str(hook_link)) == 3


def test_reinstall_removes_legacy_runtime_hook_from_stale_event(tmp_path, monkeypatch):
    from codex_chronicle.install_hooks import install_hooks
    settings = tmp_path / "settings.json"
    bin_dir = tmp_path / "bin"
    runtime_dir = tmp_path / ".codex-chronicle" / "runtime"
    bin_dir.mkdir()
    runtime_dir.mkdir(parents=True)
    runtime_binary = runtime_dir / "codex-chronicle"
    runtime_binary.write_text("#!/bin/sh\n")
    runtime_binary.chmod(0o755)
    hook_link = bin_dir / "codex-chronicle-hook"
    hook_link.symlink_to(runtime_binary)
    monkeypatch.setenv("PATH", str(bin_dir))
    settings.write_text(json.dumps({
        "hooks": {
            "SessionEnd": [{"hooks": [{"command": str(runtime_binary)}]}],
            "MyEvent": [{"matcher": "", "hooks": []}],
        },
    }))

    install_hooks(str(settings))

    data = json.loads(settings.read_text())
    assert "SessionEnd" not in data["hooks"]
    assert data["hooks"]["MyEvent"] == [{"matcher": "", "hooks": []}]


def test_custom_hooks_path_enables_sibling_config_not_real_home(tmp_path, monkeypatch):
    from codex_chronicle.install_hooks import install_hooks
    real_home = tmp_path / "real-home"
    custom = tmp_path / "custom"
    real_home.mkdir()
    custom.mkdir()
    monkeypatch.setenv("HOME", str(real_home))

    install_hooks(str(custom / "hooks.json"))

    assert (custom / "config.toml").exists()
    assert not (real_home / ".codex" / "config.toml").exists()
