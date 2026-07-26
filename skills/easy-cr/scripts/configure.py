#!/usr/bin/env python3
"""View or update the shared Easy CR editor configuration."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from easy_cr_config import (
    CONFIG_DIR,
    CONFIG_PATH,
    ENHANCED_EDITORS,
    editor_descriptor,
    read_editor,
    resolve_semantic,
    token_path_for_editor,
    write_editor,
)


SCRIPT_DIR = Path(__file__).resolve().parent
SETUP_JETBRAINS_SCRIPT = SCRIPT_DIR / "setup_jetbrains_plugin.py"
SETUP_VSCODE_SCRIPT = SCRIPT_DIR / "setup_vscode_extension.py"
CLI_EDITOR_CHOICES = ("none", "goland", "idea", "vscode")
JETBRAINS_EDITORS = frozenset({"goland", "idea"})


def configure_enhanced_editor(
    editor: str,
    config_path: Path,
    config_dir: Path,
) -> None:
    token_path = token_path_for_editor(editor, config_dir)
    if editor in JETBRAINS_EDITORS:
        command = [
            sys.executable,
            str(SETUP_JETBRAINS_SCRIPT),
            "--editor",
            editor,
            "--token-file",
            str(token_path),
        ]
    elif editor == "vscode":
        command = [
            sys.executable,
            str(SETUP_VSCODE_SCRIPT),
            "--token-file",
            str(token_path),
        ]
    else:
        raise ValueError(f"暂不支持通过 configure.py 安装编辑器：{editor}")
    result = subprocess.run(command, check=False)
    if result.returncode:
        display = editor_descriptor(editor).display_name
        raise RuntimeError(f"{display} 扩展安装失败，未修改 Easy CR 配置")
    write_editor(editor, config_path)


def status_payload(
    config_path: Path,
    token_path: Path | None = None,
    config_dir: Path | None = None,
) -> dict[str, object]:
    resolved_dir = config_dir or config_path.expanduser().parent
    semantic, warning = resolve_semantic(
        config_path,
        token_path=token_path,
        config_dir=resolved_dir if token_path is None else None,
    )
    editor = read_editor(config_path)
    mode = semantic.get("mode")
    enhanced = mode == "editor" or mode == "goland"
    return {
        "configuredEditor": editor,
        "editorReady": enhanced,
        # Backward-compatible field for older callers/tests.
        "golandReady": enhanced and editor == "goland",
        "mode": mode,
        "warning": warning,
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config-file", type=Path, default=CONFIG_PATH)
    parser.add_argument("--config-dir", type=Path, default=None)
    parser.add_argument("--token-file", type=Path, default=None)
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("status")
    set_parser = subparsers.add_parser("set")
    set_parser.add_argument("editor", choices=CLI_EDITOR_CHOICES)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    config_dir = args.config_dir or args.config_file.expanduser().parent
    try:
        if args.command == "status":
            print(json.dumps(
                status_payload(
                    args.config_file,
                    token_path=args.token_file,
                    config_dir=config_dir,
                ),
                ensure_ascii=False,
                indent=2,
            ))
            return 0
        if args.editor == "none":
            write_editor("none", args.config_file)
            print(f"Easy CR 已使用基础模式：{args.config_file.expanduser()}")
            return 0
        if args.editor not in ENHANCED_EDITORS:
            raise ValueError(f"未知编辑器：{args.editor}")
        configure_enhanced_editor(args.editor, args.config_file, config_dir)
        display = editor_descriptor(args.editor).display_name
        print(f"Easy CR 已启用 {display} 联动：{args.config_file.expanduser()}")
        print(f"请在方便时重启 {display}，使新扩展生效。")
        return 0
    except (OSError, RuntimeError, ValueError) as error:
        print(f"easy-cr configure: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
