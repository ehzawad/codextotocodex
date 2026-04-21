"""Platform service-manager integration (launchd + systemd-user).

Responsibilities:
- Write/remove launchd plist (macOS) or systemd user unit (Linux).
- Bootstrap/bootout (macOS) or enable/disable (Linux) the service.
- Pause/resume service during `codex-chronicle process` to prevent races.
- Detect mode drift (config says foreground but service loaded, etc.).

Designed to work under both macOS Tahoe (launchd) and Ubuntu 24.04 LTS
(systemd --user). Status probes (`service_running`, `service_installed`,
`mode_drift_warnings`) are best-effort — missing `launchctl`/`systemctl`
degrades to "unknown" rather than raising. Install / bootstrap surfaces
its failure: `install_service()` returns False when the manager rejected
the job, and `install-daemon` rolls the config mode back so `codex-chronicle
doctor` doesn't lie about intent. The processing lock is the correctness
boundary across all code paths.

Service files always include a full PATH in EnvironmentVariables /
Environment="PATH=..." so the daemon can find `codex` even when
launched by a service manager that doesn't source shell profiles.
"""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Optional

from .codex_cli import try_resolve_codex_binary
from .config import chronicle_dir
from .launcher import resolve_cli_invocation

_MAC_LABEL = "com.codex_chronicle.daemon"
_LINUX_UNIT = "codex-chronicle-daemon.service"

_MAC_PLIST_PATH = Path.home() / "Library" / "LaunchAgents" / f"{_MAC_LABEL}.plist"
_LINUX_UNIT_PATH = Path.home() / ".config" / "systemd" / "user" / _LINUX_UNIT


def _standard_path() -> str:
    """PATH string to bake into service unit files."""
    parts = [
        str(Path.home() / ".local" / "bin"),
        "/opt/homebrew/bin",
        "/usr/local/bin",
        "/usr/bin",
        "/bin",
        "/usr/sbin",
        "/sbin",
    ]
    # Preserve anything unique from the current PATH too (helps nvm/pyenv)
    for p in os.environ.get("PATH", "").split(os.pathsep):
        if p and p not in parts:
            parts.append(p)
    return os.pathsep.join(parts)


def _chronicle_command(*extra_args: str) -> list[str]:
    """argv used in launchd / systemd unit files."""
    return resolve_cli_invocation(*extra_args)


# ---------- macOS (launchd) ----------

def _mac_plist_contents() -> str:
    chronicle_cmd = _chronicle_command("daemon")
    home = str(Path.home())
    path_val = _standard_path()
    codex = try_resolve_codex_binary()
    codex_hint = f"    <!-- resolved codex at install: {codex} -->\n" if codex else ""
    log_path = chronicle_dir() / "daemon.log"
    args_xml = "\n".join(f"        <string>{arg}</string>" for arg in chronicle_cmd)
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
{codex_hint}    <key>Label</key>
    <string>{_MAC_LABEL}</string>
    <key>ProgramArguments</key>
    <array>
{args_xml}
    </array>
    <key>WorkingDirectory</key>
    <string>{home}</string>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>{path_val}</string>
        <key>HOME</key>
        <string>{home}</string>
    </dict>
    <key>StandardOutPath</key>
    <string>{log_path}</string>
    <key>StandardErrorPath</key>
    <string>{log_path}</string>
</dict>
</plist>
"""


def _mac_run(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(args, capture_output=True, text=True)


def _mac_bootout() -> None:
    """Bootout the service if loaded; ignore errors if not loaded."""
    uid = os.getuid()
    _mac_run(["launchctl", "bootout", f"gui/{uid}/{_MAC_LABEL}"])


def _mac_bootstrap() -> bool:
    """Bootstrap the service. Returns True on success."""
    uid = os.getuid()
    res = _mac_run(["launchctl", "bootstrap", f"gui/{uid}", str(_MAC_PLIST_PATH)])
    return res.returncode == 0


def _mac_is_loaded() -> bool:
    res = _mac_run(["launchctl", "print", f"gui/{os.getuid()}/{_MAC_LABEL}"])
    return res.returncode == 0


def _mac_is_running() -> bool:
    res = _mac_run(["launchctl", "print", f"gui/{os.getuid()}/{_MAC_LABEL}"])
    if res.returncode != 0:
        return False
    return "state = running" in res.stdout


def _mac_install() -> bool:
    """Write plist and (re)bootstrap. Returns True if launchd accepted the job."""
    _MAC_PLIST_PATH.parent.mkdir(parents=True, exist_ok=True)
    _MAC_PLIST_PATH.write_text(_mac_plist_contents())
    _mac_bootout()
    return _mac_bootstrap()


def _mac_uninstall() -> None:
    _mac_bootout()
    if _MAC_PLIST_PATH.exists():
        _MAC_PLIST_PATH.unlink()


# ---------- Linux (systemd --user) ----------

def _linux_unit_contents() -> str:
    chronicle_cmd = shlex.join(_chronicle_command("daemon"))
    path_val = _standard_path()
    return f"""[Unit]
Description=Codex Chronicle Daemon
After=default.target

[Service]
Type=simple
WorkingDirectory=%h
Environment="PATH={path_val}"
Environment="CODEX_CHRONICLE_HOME={chronicle_dir()}"
ExecStart={chronicle_cmd}
Restart=on-failure
RestartSec=10

[Install]
WantedBy=default.target
"""


def _linux_run(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(args, capture_output=True, text=True)


def _linux_is_active() -> bool:
    res = _linux_run(["systemctl", "--user", "is-active", _LINUX_UNIT])
    return res.returncode == 0


def _linux_install() -> bool:
    """Write unit and `enable --now`. Returns True if systemctl reports success."""
    _LINUX_UNIT_PATH.parent.mkdir(parents=True, exist_ok=True)
    _LINUX_UNIT_PATH.write_text(_linux_unit_contents())
    _linux_run(["systemctl", "--user", "daemon-reload"])
    res = _linux_run(["systemctl", "--user", "enable", "--now", _LINUX_UNIT])
    return res.returncode == 0


def _linux_uninstall() -> None:
    _linux_run(["systemctl", "--user", "disable", "--now", _LINUX_UNIT])
    if _LINUX_UNIT_PATH.exists():
        _LINUX_UNIT_PATH.unlink()
    _linux_run(["systemctl", "--user", "daemon-reload"])


# ---------- Public API ----------

def platform_key() -> str:
    if sys.platform == "darwin":
        return "macos"
    if sys.platform.startswith("linux"):
        return "linux"
    return "other"


def install_service() -> bool:
    """Install and start the service on this platform. Idempotent.

    Returns True if the service manager accepted the job. False means
    the file was written but bootstrap/enable failed — caller should
    surface this to the user via `codex-chronicle doctor`.
    """
    p = platform_key()
    if p == "macos":
        return _mac_install()
    if p == "linux":
        return _linux_install()
    raise RuntimeError(
        f"Unsupported platform {sys.platform}; run `codex-chronicle daemon` manually."
    )


def uninstall_service() -> None:
    """Stop and remove the service on this platform. Idempotent."""
    p = platform_key()
    if p == "macos":
        _mac_uninstall()
    elif p == "linux":
        _linux_uninstall()
    else:
        # Nothing to uninstall on unknown platform
        return


def service_installed() -> bool:
    """Is the service file present on disk?"""
    p = platform_key()
    if p == "macos":
        return _MAC_PLIST_PATH.exists()
    if p == "linux":
        return _LINUX_UNIT_PATH.exists()
    return False


def service_running() -> bool:
    """Is the service currently loaded/active per the service manager?"""
    p = platform_key()
    if p == "macos":
        if not shutil.which("launchctl"):
            return False
        return _mac_is_running()
    if p == "linux":
        if not shutil.which("systemctl"):
            return False
        return _linux_is_active()
    return False


def service_file_path() -> Optional[Path]:
    """Path to the service unit file for this platform."""
    p = platform_key()
    if p == "macos":
        return _MAC_PLIST_PATH
    if p == "linux":
        return _LINUX_UNIT_PATH
    return None


def pause_service() -> bool:
    """Stop the service without removing the file (for `codex-chronicle process`).

    Returns True if the service was paused (and therefore should be resumed),
    False otherwise.
    """
    p = platform_key()
    if p == "macos":
        if not shutil.which("launchctl"):
            return False
        was_running = _mac_is_running()
        _mac_bootout()
        return was_running
    if p == "linux":
        if not shutil.which("systemctl"):
            return False
        was_active = _linux_is_active()
        if was_active:
            _linux_run(["systemctl", "--user", "stop", _LINUX_UNIT])
        return was_active
    return False


def resume_service() -> None:
    """Re-bootstrap / re-start the service. Called after a pause."""
    p = platform_key()
    if p == "macos":
        if _MAC_PLIST_PATH.exists() and shutil.which("launchctl"):
            _mac_bootstrap()
    elif p == "linux":
        if _LINUX_UNIT_PATH.exists() and shutil.which("systemctl"):
            _linux_run(["systemctl", "--user", "start", _LINUX_UNIT])


def mode_drift_warnings() -> list[str]:
    """Return human-readable warnings about config/service mismatch.

    Call from `codex-chronicle doctor`.
    """
    from .mode import get_processing_mode  # local import avoids cycle

    warnings: list[str] = []
    mode = get_processing_mode()
    installed = service_installed()
    running = service_running()

    if mode == "foreground" and (installed or running):
        bits = []
        if installed:
            bits.append("service file present")
        if running:
            bits.append("daemon running")
        warnings.append(
            f"Mode=foreground but {', '.join(bits)} — "
            "run `codex-chronicle uninstall-daemon` to fix."
        )
    elif mode == "background" and not installed:
        warnings.append(
            "Mode=background but service file missing — "
            "run `codex-chronicle install-daemon` to fix."
        )
    elif mode == "background" and installed and not running:
        warnings.append(
            "Mode=background and service file present, but daemon not running. "
            "Check daemon.log; re-run `codex-chronicle install-daemon` to reinstall the service."
        )
    return warnings
