#!/usr/bin/env python3
"""Install the repository Easy CR CLI as a user-level symlink."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = REPO_ROOT / "bin" / "easy-cr"
DEFAULT_DESTINATION = Path.home() / ".local" / "bin" / "easy-cr"


def is_easy_cr_source(path: Path) -> bool:
    parts = path.resolve(strict=False).parts
    return len(parts) >= 3 and parts[-3:] == ("easy-cr", "bin", "easy-cr")


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


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--destination", type=Path, default=DEFAULT_DESTINATION)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        result = install_symlink(args.source, args.destination)
        labels = {
            "created": "已安装",
            "updated": "已更新",
            "unchanged": "已是最新",
        }
        print(f"Easy CR CLI {labels[result]}：{args.destination.expanduser()}")
        return 0
    except (OSError, RuntimeError) as error:
        print(f"easy-cr install: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
