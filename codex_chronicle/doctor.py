"""`codex-chronicle doctor` — read-only diagnostic.

Reports mode, resolved Codex binary, daemon status, service drift,
marker counts, and pending sessions. Used after install and when
debugging why sessions aren't being processed.

Never mutates state. `--json` emits machine-readable output for CI / tests.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from typing import Any, Sequence

from . import service
from .codex_cli import try_resolve_codex_binary
from .config import (
    chronicle_dir, config_file,
    processed_dir, processing_lock_path,
)
from .locks import daemon_is_running, processing_lock_held
from .mode import get_processing_mode
from .storage import is_succeeded, is_terminal_failure, list_failed
from .source import iter_session_files, read_session_meta


def _codex_version(codex_bin) -> str | None:
    if codex_bin is None:
        return None
    try:
        res = subprocess.run(
            [str(codex_bin), "--version"],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    text = (res.stdout or res.stderr or "").strip()
    return text or None


def _count_sessions() -> dict:
    """Return counts of processed_ok / terminal_failure / unprocessed JSONLs."""
    ok = 0
    term = 0
    pending = 0
    for jsonl in iter_session_files():
        sid = read_session_meta(jsonl).session_id
        if is_succeeded(sid):
            ok += 1
        elif is_terminal_failure(sid):
            term += 1
        else:
            pending += 1
    return {"processed_ok": ok, "terminal_failure": term, "unprocessed": pending}


def collect_diagnostics() -> dict[str, Any]:
    """Pure state collector — returns a fully serializable dict.

    All filesystem paths are converted to strings. Drift warnings are
    included as a list of human-readable strings. Renderers (text / JSON)
    consume this dict without mutating it.
    """
    from . import __version__
    from .config import load_config

    mode = get_processing_mode()
    codex_bin = try_resolve_codex_binary()
    running, pid = daemon_is_running()
    svc_path = service.service_file_path()
    failed_records = list_failed()
    terminal_count = sum(1 for r in failed_records if r.get("terminal"))
    sessions = _count_sessions()

    processed_marker_count = (
        len(list(processed_dir().glob("*"))) if processed_dir().exists() else 0
    )

    drift_warnings = list(service.mode_drift_warnings())
    # Surface a corrupt config.json loudly. The rest of the system falls
    # back to DEFAULT_CONFIG silently (so the daemon doesn't crash on every
    # tick), but the user needs to know.
    cfg = load_config()
    config_error = cfg.get("_load_error")
    if config_error:
        drift_warnings.insert(0, f"config load error: {config_error}")

    return {
        "schema_version": 1,
        "ok": (
            not drift_warnings
            and codex_bin is not None
            and config_error is None
        ),
        "version": __version__,
        "chronicle_binary": shutil.which("codex-chronicle"),
        "mode": mode,
        "config_path": str(config_file()),
        "codex": {
            "resolved": str(codex_bin) if codex_bin else None,
            "version": _codex_version(codex_bin),
            "path_env": os.environ.get("PATH", ""),
        },
        "daemon": {
            "running": running,
            "pid": pid,
        },
        "service": {
            "file": str(svc_path) if svc_path else None,
            "installed": service.service_installed(),
            "running": service.service_running(),
        },
        "locks": {
            "pid_file": str(chronicle_dir() / "daemon.pid"),
            "processing_lock": {
                "path": str(processing_lock_path()),
                "held": processing_lock_held(),
            },
        },
        "sessions": sessions,
        "markers": {
            "processed_entries": processed_marker_count,
            "failed_entries": len(failed_records),
            "failed_terminal": terminal_count,
            "failed_retryable": len(failed_records) - terminal_count,
        },
        "failed_sample": [
            {
                "session_id": r.get("session_id"),
                "attempts": r.get("attempts"),
                "terminal": r.get("terminal"),
                "last_error_kind": r.get("last_error_kind"),
                "last_error_message": (r.get("last_error_message") or "")[:200],
            }
            for r in failed_records if r.get("terminal")
        ][:5],
        "drift_warnings": drift_warnings,
    }


def _section(title: str) -> None:
    print(f"\n{title}")
    print("─" * len(title))


def print_human(data: dict[str, Any]) -> None:
    """Render diagnostics as a human-friendly report."""
    _section("codex-chronicle doctor")
    print(f"version:     {data['version']}")
    print(f"binary:      {data['chronicle_binary'] or '(not on PATH)'}")
    print(f"mode:        {data['mode']}")
    print(f"config:      {data['config_path']}")

    _section("codex binary")
    resolved = data["codex"]["resolved"]
    if resolved:
        print(f"resolved:    {resolved}")
        if data["codex"].get("version"):
            print(f"version:     {data['codex']['version']}")
    else:
        print("resolved:    NOT FOUND — Codex Chronicle cannot summarize",
              file=sys.stderr)
    print(f"PATH:        {data['codex']['path_env']}")

    _section("daemon")
    d = data["daemon"]
    if d["running"]:
        print(f"running:     yes (pid {d['pid']})")
    else:
        print("running:     no")
    svc = data["service"]
    print(f"service file: {svc['file'] or '(unsupported platform)'} "
          f"({'installed' if svc['installed'] else 'absent'})")
    print(f"service status: {'active' if svc['running'] else 'inactive'}")

    _section("drift")
    warnings = data["drift_warnings"]
    if not warnings:
        print("(no drift detected)")
    else:
        for w in warnings:
            print(f"!  {w}")

    _section("locks")
    print(f"daemon pid file: {data['locks']['pid_file']}")
    plk = data["locks"]["processing_lock"]
    print(f"processing lock: {plk['path']} "
          f"({'HELD' if plk['held'] else 'free'})")

    _section("sessions")
    s = data["sessions"]
    m = data["markers"]
    print("source JSONLs (under ~/.codex/sessions/): ")
    print(f"  processed OK:      {s['processed_ok']}")
    print(f"  terminal failure:  {s['terminal_failure']}")
    print(f"  unprocessed:       {s['unprocessed']}")
    print("markers:")
    print(f"  .processed/        {m['processed_entries']} entries")
    print(f"  .failed/           {m['failed_entries']} entries "
          f"({m['failed_terminal']} terminal, {m['failed_retryable']} retryable)")

    sample = data["failed_sample"]
    if sample:
        _section("terminal failures (first 5)")
        for rec in sample:
            print(f"  {(rec.get('session_id') or '?')[:8]}  "
                  f"attempts={rec.get('attempts', 0)}  "
                  f"kind={rec.get('last_error_kind', '?')}")
            msg = rec.get("last_error_message") or ""
            if msg:
                print(f"    {msg[:140]}")
        if m["failed_terminal"] > len(sample):
            print(f"  ... and {m['failed_terminal'] - len(sample)} more")
        print()
        print("To retry all terminal failures after fixing the root cause:")
        print("  codex-chronicle process --retry-failed --workers 5")

    print()


def run(argv: Sequence[str] | None = None) -> int:
    """Entry point. Returns 0 iff diagnostics `ok` is true — i.e. no drift
    warnings, `codex` resolved, and config.json parsed cleanly.

    `argv` lets tests pass flags without mutating sys.argv. When None,
    uses sys.argv[1:] after the top-level dispatcher strips the subcommand.
    """
    parser = argparse.ArgumentParser(
        prog="codex-chronicle doctor",
        description="Diagnose Codex Chronicle configuration and daemon health.",
    )
    parser.add_argument(
        "--json", action="store_true",
        help="Emit diagnostics as a JSON document on stdout.",
    )
    args = parser.parse_args(argv)

    data = collect_diagnostics()

    if args.json:
        # Paths already stringified in collect_diagnostics; default=str
        # is a safety net for anything unexpected.
        json.dump(data, sys.stdout, indent=2, default=str)
        sys.stdout.write("\n")
    else:
        print_human(data)

    return 0 if data["ok"] else 1
