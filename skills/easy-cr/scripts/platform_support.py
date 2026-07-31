#!/usr/bin/env python3
"""Small cross-platform path and permission helpers for Easy CR."""

from __future__ import annotations

import os
import stat
import sys
from collections.abc import Mapping
from pathlib import Path


def is_windows(platform: str | None = None) -> bool:
    return (platform or sys.platform).startswith("win")


def default_config_dir(
    *,
    home: Path | None = None,
    environ: Mapping[str, str] | None = None,
    platform: str | None = None,
) -> Path:
    """Return the native per-user Easy CR configuration directory."""
    values = os.environ if environ is None else environ
    resolved_home = (home or Path.home()).expanduser()
    if is_windows(platform):
        base = values.get("APPDATA")
        return Path(base) / "easy-cr" if base else (
            resolved_home / "AppData" / "Roaming" / "easy-cr"
        )
    base = values.get("XDG_CONFIG_HOME")
    return Path(base) / "easy-cr" if base else resolved_home / ".config" / "easy-cr"


def default_cli_destination(
    *,
    home: Path | None = None,
    platform: str | None = None,
) -> Path:
    resolved_home = (home or Path.home()).expanduser()
    name = "easy-cr.cmd" if is_windows(platform) else "easy-cr"
    return resolved_home / ".local" / "bin" / name


def windows_startup_dir(
    *,
    home: Path | None = None,
    environ: Mapping[str, str] | None = None,
) -> Path:
    values = os.environ if environ is None else environ
    resolved_home = (home or Path.home()).expanduser()
    app_data = Path(
        values.get("APPDATA")
        or resolved_home / "AppData" / "Roaming"
    )
    return (
        app_data
        / "Microsoft"
        / "Windows"
        / "Start Menu"
        / "Programs"
        / "Startup"
    )


def apply_permissions(path: Path, mode: int) -> None:
    """Apply POSIX permissions when meaningful; tolerate inherited Windows ACLs."""
    try:
        path.chmod(mode)
    except OSError:
        if os.name != "nt":
            raise


def private_permissions_ok(path: Path, mode: int = 0o600) -> bool:
    if not path.is_file():
        return False
    if os.name == "nt":
        # Windows access is governed by ACLs, not POSIX mode bits exposed by stat().
        return True
    return stat.S_IMODE(path.stat().st_mode) == mode
