"""Unit tests for codex_chronicle.mode."""
from __future__ import annotations

import json

import pytest


@pytest.fixture
def isolated_config(tmp_path, monkeypatch):
    fake_home = tmp_path / "home"
    (fake_home / ".codex-chronicle").mkdir(parents=True)
    monkeypatch.setenv("HOME", str(fake_home))
    import importlib
    import codex_chronicle.config
    import codex_chronicle.mode
    importlib.reload(codex_chronicle.config)
    importlib.reload(codex_chronicle.mode)
    yield fake_home / ".codex-chronicle"
    importlib.reload(codex_chronicle.config)
    importlib.reload(codex_chronicle.mode)


def test_default_mode_is_foreground(isolated_config):
    from codex_chronicle import mode
    assert mode.get_processing_mode() == "foreground"
    assert mode.is_foreground_mode()
    assert not mode.is_background_mode()


def test_set_mode_background(isolated_config):
    from codex_chronicle import mode
    mode.set_processing_mode("background")
    assert mode.get_processing_mode() == "background"
    assert mode.is_background_mode()


def test_roundtrip_to_foreground(isolated_config):
    from codex_chronicle import mode
    mode.set_processing_mode("background")
    mode.set_processing_mode("foreground")
    assert mode.is_foreground_mode()


def test_invalid_mode_rejected(isolated_config):
    from codex_chronicle import mode
    with pytest.raises(ValueError):
        mode.set_processing_mode("sideways")


def test_persists_across_import(isolated_config, tmp_path):
    from codex_chronicle import mode
    mode.set_processing_mode("background")
    import importlib
    import codex_chronicle.mode
    importlib.reload(codex_chronicle.mode)
    assert codex_chronicle.mode.get_processing_mode() == "background"
