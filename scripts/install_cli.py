#!/usr/bin/env python3
"""Install the repository Easy CR CLI as a user-level command."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPO_ROOT / "skills" / "easy-cr" / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from platform_support import default_cli_destination, is_windows  # noqa: E402


DEFAULT_SOURCE = REPO_ROOT / "bin" / "easy-cr"
DEFAULT_DESTINATION = default_cli_destination()
WINDOWS_MARKER = ":: Easy CR source launcher"


def is_easy_cr_source(path: Path) -> bool:
    parts = path.resolve(strict=False).parts
    return (
        len(parts) >= 3
        and parts[-3].lower() == "easy-cr"
        and parts[-2].lower() == "bin"
        and parts[-1].lower() == "easy-cr"
    )


def install_symlink(source: Path, destination: Path) -> str:
    source = source.expanduser().resolve()
    destination = destination.expanduser()
    if not source.is_file():
        raise RuntimeError(f"CLI 源文件不存在：{source}")

    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.is_symlink():
        current = destination.resolve(strict=False)
        if current == source:
            return "unchanged"
        if not is_easy_cr_source(current):
            raise RuntimeError(
                f"拒绝覆盖无关软链：{destination} -> {os.readlink(destination)}"
            )
        temporary = destination.with_name(f".{destination.name}.new")
        temporary.unlink(missing_ok=True)
        temporary.symlink_to(source)
        os.replace(temporary, destination)
        return "updated"
    if destination.exists():
        raise RuntimeError(f"拒绝覆盖已有文件：{destination}")

    destination.symlink_to(source)
    return "created"


def windows_launcher(source: Path, python: Path = Path(sys.executable)) -> str:
    return "\r\n".join([
        "@echo off",
        WINDOWS_MARKER,
        f'"{python}" -X utf8 "{source}" %*',
        "exit /b %ERRORLEVEL%",
        "",
    ])


def install_windows_launcher(
    source: Path,
    destination: Path,
    *,
    python: Path = Path(sys.executable),
) -> str:
    source = source.expanduser().resolve()
    destination = destination.expanduser()
    if not source.is_file():
        raise RuntimeError(f"CLI 源文件不存在：{source}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    desired = windows_launcher(source, python)
    if destination.exists():
        try:
            current = destination.read_text(encoding="utf-8")
        except OSError as error:
            raise RuntimeError(f"读取已有命令失败：{destination}") from error
        if current.replace("\r\n", "\n") == desired.replace("\r\n", "\n"):
            return "unchanged"
        if WINDOWS_MARKER not in current:
            raise RuntimeError(f"拒绝覆盖已有文件：{destination}")
        result = "updated"
    else:
        result = "created"
    temporary = destination.with_name(f".{destination.name}.new")
    temporary.write_text(desired, encoding="utf-8", newline="")
    os.replace(temporary, destination)
    return result


def install_command(source: Path, destination: Path) -> str:
    if is_windows():
        return install_windows_launcher(source, destination)
    return install_symlink(source, destination)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--destination", type=Path, default=DEFAULT_DESTINATION)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        result = install_command(args.source, args.destination)
        labels = {
            "created": "已安装",
            "updated": "已更新",
            "unchanged": "已是最新",
        }
        print(f"Easy CR CLI {labels[result]}：{args.destination.expanduser()}")
        if is_windows():
            print("如命令尚不可用，请将上述目录加入用户 PATH，或优先使用 npm 全局安装。")
        return 0
    except (OSError, RuntimeError) as error:
        print(f"easy-cr install: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
