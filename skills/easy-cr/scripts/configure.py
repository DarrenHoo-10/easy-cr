#!/usr/bin/env python3
"""View or update the shared Easy CR editor configuration."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from easy_cr_config import CONFIG_PATH, TOKEN_PATH, read_editor, resolve_semantic, write_editor


SCRIPT_DIR = Path(__file__).resolve().parent
SETUP_SCRIPT = SCRIPT_DIR / "setup_goland_plugin.py"


def configure_goland(config_path: Path, token_path: Path) -> None:
    result = subprocess.run(
        [sys.executable, str(SETUP_SCRIPT), "--token-file", str(token_path)],
        check=False,
    )
    if result.returncode:
        raise RuntimeError("GoLand 扩展安装失败，未修改 Easy CR 配置")
    write_editor("goland", config_path)


def status_payload(config_path: Path, token_path: Path) -> dict[str, object]:
    semantic, warning = resolve_semantic(config_path, token_path)
    return {
        "configuredEditor": read_editor(config_path),
        "golandReady": semantic.get("mode") == "goland",
        "warning": warning,
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config-file", type=Path, default=CONFIG_PATH)
    parser.add_argument("--token-file", type=Path, default=TOKEN_PATH)
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("status")
    set_parser = subparsers.add_parser("set")
    set_parser.add_argument("editor", choices=("none", "goland"))
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        if args.command == "status":
            print(json.dumps(
                status_payload(args.config_file, args.token_file),
                ensure_ascii=False,
                indent=2,
            ))
            return 0
        if args.editor == "none":
            write_editor("none", args.config_file)
            print(f"Easy CR 已使用基础模式：{args.config_file.expanduser()}")
            return 0
        configure_goland(args.config_file, args.token_file)
        print(f"Easy CR 已启用 GoLand 联动：{args.config_file.expanduser()}")
        print("请在方便时重启 GoLand，使新扩展生效。")
        return 0
    except (OSError, RuntimeError, ValueError) as error:
        print(f"easy-cr configure: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
