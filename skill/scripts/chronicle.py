#!/usr/bin/env python3
"""Run Codex Chronicle from this source checkout.

The skill is intended to be symlinked into ~/.agents/skills/codex-chronicle.
Resolving this file's real path lets it import the checkout even when the
global codex-chronicle executable has not been installed.
"""
from __future__ import annotations

import sys
from pathlib import Path


def main() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(repo_root))
    from codex_chronicle.__main__ import main as chronicle_main

    sys.argv = ["codex-chronicle", *sys.argv[1:]]
    chronicle_main()


if __name__ == "__main__":
    main()
