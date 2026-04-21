from __future__ import annotations

import pytest


def test_daemon_rejects_zero_concurrency():
    from codex_chronicle.daemon import _validated_concurrency
    with pytest.raises(ValueError, match="config.concurrency must be >= 1"):
        _validated_concurrency({"concurrency": 0})
