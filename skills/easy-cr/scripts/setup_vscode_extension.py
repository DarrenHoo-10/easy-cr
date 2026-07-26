#!/usr/bin/env python3
"""Build and install the restricted Easy CR extension into local VS Code."""

from __future__ import annotations

import argparse
import os
import secrets
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from easy_cr_config import CONFIG_DIR


SKILL_DIR = Path(__file__).resolve().parent.parent
EXTENSION_SOURCE = SKILL_DIR / "assets" / "vscode-extension"
TOKEN_FILE = "vscode-token"
VSCODE_APP = Path("/Applications/Visual Studio Code.app")
VSCODE_APP_CODE = VSCODE_APP / "Contents" / "Resources" / "app" / "bin" / "code"
USER_BIN = Path.home() / ".local" / "bin"


def run(command: list[str], *, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        command,
        cwd=str(cwd) if cwd else None,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode:
        detail = result.stderr.strip() or result.stdout.strip() or "command failed"
        raise RuntimeError(detail)
    return result


def ensure_token(path: Path) -> Path:
    path = path.expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.parent.chmod(0o700)
    if not path.exists():
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w") as stream:
            stream.write(secrets.token_urlsafe(32))
    path.chmod(0o600)
    return path


def npm_command() -> str:
    command = shutil.which("npm")
    if not command:
        raise RuntimeError("未找到 npm，无法构建 VS Code 扩展")
    return command


def candidate_code_commands() -> list[Path]:
    candidates: list[Path] = []
    which = shutil.which("code")
    if which:
        candidates.append(Path(which))
    candidates.extend([
        VSCODE_APP_CODE,
        Path("/usr/local/bin/code"),
        Path("/opt/homebrew/bin/code"),
        USER_BIN / "code",
    ])
    # Preserve order while dropping duplicates.
    unique: list[Path] = []
    seen: set[str] = set()
    for candidate in candidates:
        key = str(candidate)
        if key in seen:
            continue
        seen.add(key)
        unique.append(candidate)
    return unique


def is_usable_code_command(command: Path) -> bool:
    resolved = command.expanduser()
    if not resolved.is_file():
        which = shutil.which(str(resolved))
        if which is None:
            return False
        resolved = Path(which)
    try:
        result = subprocess.run(
            [str(resolved), "--version"],
            text=True,
            capture_output=True,
            check=False,
            timeout=8,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0 and bool(result.stdout.strip() or result.stderr.strip())


def resolve_code_command(explicit: Path | None = None) -> Path:
    """Locate a usable VS Code CLI, preferring PATH then the macOS app bundle."""
    ordered: list[Path] = []
    if explicit is not None:
        ordered.append(explicit)
    ordered.extend(candidate_code_commands())
    seen: set[str] = set()
    for candidate in ordered:
        key = str(candidate)
        if key in seen:
            continue
        seen.add(key)
        if is_usable_code_command(candidate):
            if candidate.is_file():
                return candidate.resolve()
            which = shutil.which(str(candidate))
            if which:
                return Path(which).resolve()
    raise RuntimeError(
        "未找到可用的 VS Code CLI。\n"
        "请先安装 macOS 版 Visual Studio Code，或在 VS Code 中执行：\n"
        "  Shell Command: Install 'code' command in PATH"
    )


def ensure_user_code_shim(code_command: Path) -> Path | None:
    """Best-effort: expose the discovered CLI as ~/.local/bin/code when missing from PATH.

    Never overwrites an existing unrelated file/symlink. Returns the shim path when
    created or already correctly linked; otherwise None.
    """
    if shutil.which("code"):
        return None
    target = code_command.expanduser().resolve()
    if not target.is_file():
        return None
    USER_BIN.mkdir(parents=True, exist_ok=True)
    shim = USER_BIN / "code"
    if shim.is_symlink():
        try:
            if shim.resolve() == target:
                return shim
        except OSError:
            pass
        return None
    if shim.exists():
        return None
    try:
        shim.symlink_to(target)
    except OSError:
        return None
    return shim


def build_vsix(output: Path) -> Path:
    if not EXTENSION_SOURCE.is_dir():
        raise RuntimeError("VS Code 扩展源码缺失")
    output = output.expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    npm = npm_command()
    with tempfile.TemporaryDirectory(prefix="easy-cr-vscode-") as temp:
        work = Path(temp) / "extension"
        shutil.copytree(
            EXTENSION_SOURCE,
            work,
            ignore=shutil.ignore_patterns(
                "node_modules",
                "dist",
                "out",
                "easy-cr.vsix",
                ".vscode",
            ),
        )
        run([npm, "install", "--no-fund", "--no-audit"], cwd=work)
        run([npm, "run", "compile"], cwd=work)
        run([npm, "test"], cwd=work)
        run([npm, "run", "bundle"], cwd=work)
        run([npm, "run", "package"], cwd=work)
        built = work / "easy-cr.vsix"
        if not built.is_file():
            raise RuntimeError("vsce 未生成 easy-cr.vsix")
        shutil.copy2(built, output)
    return output


def install_vsix(vsix: Path, code_command: Path) -> None:
    run([
        str(code_command),
        "--install-extension",
        str(vsix),
        "--force",
    ])


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--code",
        type=Path,
        default=None,
        help="VS Code CLI 路径；默认自动从 PATH 或 Visual Studio Code.app 发现",
    )
    parser.add_argument("--token-file", type=Path, default=CONFIG_DIR / TOKEN_FILE)
    parser.add_argument("--build-only", type=Path)
    parser.add_argument(
        "--no-path-shim",
        action="store_true",
        help="不在 ~/.local/bin 创建 code 软链",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        with tempfile.TemporaryDirectory(prefix="easy-cr-vscode-build-") as temp:
            vsix = Path(temp) / "easy-cr.vsix"
            built = build_vsix(vsix if args.build_only is None else args.build_only)
            if args.build_only is not None:
                print(built.resolve())
                return 0
            code_command = resolve_code_command(args.code)
            token = ensure_token(args.token_file)
            install_vsix(built, code_command)
            shim = None if args.no_path_shim else ensure_user_code_shim(code_command)
            print("已安装 Easy CR Visual Studio Code 扩展")
            print(f"使用 CLI：{code_command}")
            if shim is not None:
                print(f"已配置用户 PATH 命令：{shim}")
            elif not shutil.which("code"):
                print(
                    "提示：当前 shell 仍找不到 code。"
                    "可重新打开终端，或确认 ~/.local/bin 已在 PATH 中。"
                )
            print(f"本机 token：{token}")
            print("请手动重启 VS Code 一次使新扩展生效。")
            return 0
    except (OSError, RuntimeError) as error:
        print(f"easy-cr setup: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
