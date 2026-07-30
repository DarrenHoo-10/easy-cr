#!/usr/bin/env python3
"""Initialize and diagnose Easy CR for Codex, Claude Code, and editors."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from easy_cr_config import (
    CONFIG_DIR,
    CONFIG_PATH,
    ENHANCED_EDITORS,
    PROTOCOL_VERSION,
    VALID_EDITORS,
    ConfigError,
    editor_descriptor,
    launch_editor,
    read_editor,
    read_token,
    token_path_for_editor,
    write_editor,
)
from setup_jetbrains_plugin import (
    JETBRAINS_EDITORS,
    jetbrains_editor,
    newest_plugins_dir,
)
from setup_vscode_extension import (
    VSCODE_APP,
    resolve_code_command,
)
from easy_cr_helper import (
    HELPER_ENDPOINT,
    LAUNCH_AGENT_PATH,
    MASTER_TOKEN_PATH,
    helper_health,
    install_helper_service,
)
from review_comments import (
    comments_markdown,
    extract_comments,
    mark_batch_resolved,
    replace_comments_block,
)


VERSION = "1.4.3"
SKILL_DIR = SCRIPT_DIR.parent
REPO_ROOT = SKILL_DIR.parents[1]
SETUP_JETBRAINS_SCRIPT = SCRIPT_DIR / "setup_jetbrains_plugin.py"
SETUP_VSCODE_SCRIPT = SCRIPT_DIR / "setup_vscode_extension.py"
INSTALL_CLI_SCRIPT = REPO_ROOT / "scripts" / "install_cli.py"
CODEX_APP_COMMAND = Path("/Applications/ChatGPT.app/Contents/Resources/codex")
CLI_EDITOR_CHOICES = tuple(sorted(VALID_EDITORS))
JETBRAINS_EDITOR_IDS = frozenset(JETBRAINS_EDITORS)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="easy-cr", description=__doc__)
    parser.add_argument("--version", action="version", version=f"easy-cr {VERSION}")
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser("init", help="配置已安装客户端和编辑器")
    init_parser.add_argument("--editor", choices=CLI_EDITOR_CHOICES)
    init_parser.add_argument(
        "--client",
        choices=("codex", "claude"),
        action="append",
        default=[],
    )
    init_parser.add_argument("--non-interactive", action="store_true")

    status_parser = subparsers.add_parser("status", help="查看当前配置")
    status_parser.add_argument("--json", action="store_true")

    config_parser = subparsers.add_parser("config", help="修改共享配置")
    config_subparsers = config_parser.add_subparsers(
        dest="config_command",
        required=True,
    )
    editor_parser = config_subparsers.add_parser("editor")
    editor_parser.add_argument("editor", choices=CLI_EDITOR_CHOICES)
    editor_parser.add_argument(
        "--no-launch",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    editor_parser.add_argument(
        "--project",
        type=Path,
        default=None,
        help=argparse.SUPPRESS,
    )

    open_parser = subparsers.add_parser(
        "open",
        help="启动当前配置的编辑器并打开项目",
    )
    open_parser.add_argument(
        "--project",
        type=Path,
        default=None,
        help="要打开的项目路径，默认当前目录",
    )

    doctor_parser = subparsers.add_parser("doctor", help="诊断本地安装")
    doctor_parser.add_argument("--json", action="store_true")
    doctor_parser.add_argument(
        "--launch",
        action="store_true",
        help="若增强编辑器 runtime 未就绪，尝试启动编辑器",
    )

    comments_parser = subparsers.add_parser(
        "comments",
        help="读取评审 HTML 中的人类评论",
    )
    comments_parser.add_argument("report", type=Path)
    comments_parser.add_argument("--json", action="store_true")
    comments_parser.add_argument(
        "--resolve-batch",
        help="将指定 AI 处理批次中的评论标记为已解决",
    )
    comments_parser.add_argument(
        "--reply",
        help="解决批次时写入每条评论的 AI 处理结果回复",
    )

    args = parser.parse_args(argv)
    if (
        args.command == "init"
        and args.non_interactive
        and args.editor is None
    ):
        parser.error("init --non-interactive 必须显式提供 --editor")
    return args


def detect_client_commands() -> dict[str, Path | None]:
    codex = shutil.which("codex")
    if codex:
        codex_path: Path | None = Path(codex)
    elif CODEX_APP_COMMAND.is_file():
        codex_path = CODEX_APP_COMMAND
    else:
        codex_path = None
    claude = shutil.which("claude")
    return {
        "codex": codex_path,
        "claude": Path(claude) if claude else None,
    }


def atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        dir=path.parent,
        text=True,
    )
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "w") as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def atomic_write_text(path: Path, content: str) -> None:
    descriptor, name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        dir=path.parent,
    )
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "w") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.chmod(stat.S_IMODE(path.stat().st_mode))
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def remove_personal_codex_plugin(marketplace_path: Path) -> bool:
    """Remove the legacy Easy CR entry from Codex's personal marketplace."""
    try:
        payload = json.loads(marketplace_path.read_text())
    except FileNotFoundError:
        return False
    except (OSError, json.JSONDecodeError) as error:
        raise RuntimeError(f"读取 Codex marketplace 失败：{error}") from error
    if not isinstance(payload, dict):
        raise RuntimeError("Codex marketplace 顶层必须为 JSON 对象")
    plugins = payload.get("plugins", [])
    if not isinstance(plugins, list):
        raise RuntimeError("Codex marketplace plugins 必须为数组")
    filtered = [
        item
        for item in plugins
        if not (isinstance(item, dict) and item.get("name") == "easy-cr")
    ]
    if len(filtered) == len(plugins):
        return False
    payload["plugins"] = filtered
    atomic_write_json(marketplace_path, payload)
    return True


def codex_marketplace_path(command: Path, name: str = "easy-cr") -> str | None:
    result = run(
        [str(command), "plugin", "marketplace", "list", "--json"],
        allow_failure=True,
    )
    if result.returncode:
        return None
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        return None
    items = payload if isinstance(payload, list) else payload.get("marketplaces", [])
    for item in items:
        if not isinstance(item, dict) or item.get("name") != name:
            continue
        source = item.get("marketplaceSource") or {}
        return (
            item.get("root")
            or item.get("path")
            or source.get("source")
            or source.get("path")
        )
    return None


def run(command: list[str], *, allow_failure: bool = False) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(command, text=True, capture_output=True, check=False)
    if result.returncode and not allow_failure:
        detail = result.stderr.strip() or result.stdout.strip() or "命令执行失败"
        raise RuntimeError(f"{' '.join(command)}: {detail}")
    return result


def configure_codex(command: Path, repo_root: Path, home: Path) -> None:
    repo_root = repo_root.resolve()
    current = codex_marketplace_path(command)
    if current and Path(current).expanduser().resolve() != repo_root:
        run([str(command), "plugin", "marketplace", "remove", "easy-cr"])
        current = None
    if current is None:
        run([
            str(command),
            "plugin",
            "marketplace",
            "add",
            str(repo_root),
        ])
    run([str(command), "plugin", "add", "easy-cr@easy-cr"])
    run(
        [str(command), "plugin", "remove", "easy-cr@personal"],
        allow_failure=True,
    )
    remove_personal_codex_plugin(
        home / ".agents" / "plugins" / "marketplace.json"
    )


def claude_marketplace_path(command: Path) -> str | None:
    result = run(
        [str(command), "plugin", "marketplace", "list", "--json"],
        allow_failure=True,
    )
    if result.returncode:
        return None
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        return None
    items = payload if isinstance(payload, list) else payload.get("marketplaces", [])
    for item in items:
        if isinstance(item, dict) and item.get("name") == "easy-cr":
            source = item.get("source") or {}
            if isinstance(source, dict):
                return source.get("path") or source.get("location")
            return item.get("path")
    return None


def configure_claude(command: Path, repo_root: Path) -> None:
    current = claude_marketplace_path(command)
    if current and Path(current).expanduser().resolve() != repo_root.resolve():
        run([str(command), "plugin", "marketplace", "remove", "easy-cr"])
        current = None
    if not current:
        run([
            str(command),
            "plugin",
            "marketplace",
            "add",
            str(repo_root.resolve()),
        ])

    installed = run(
        [str(command), "plugin", "list", "--json"],
        allow_failure=True,
    )
    if installed.returncode == 0 and "easy-cr" in installed.stdout:
        run([str(command), "plugin", "update", "easy-cr@easy-cr"])
    else:
        run([
            str(command),
            "plugin",
            "install",
            "easy-cr@easy-cr",
            "--scope",
            "user",
        ])


def install_cli() -> None:
    run([sys.executable, str(INSTALL_CLI_SCRIPT)])


def configure_editor(
    editor: str,
    config_path: Path = CONFIG_PATH,
    config_dir: Path = CONFIG_DIR,
) -> bool:
    """Select an editor, installing its adapter only when setup is incomplete.

    Returns True when an adapter installation was performed.
    """
    if editor == "none":
        write_editor("none", config_path)
        return False
    if editor_setup_ready(editor, config_dir=config_dir):
        write_editor(editor, config_path)
        return False
    token_path = token_path_for_editor(editor, config_dir)
    if editor in JETBRAINS_EDITOR_IDS:
        result = run([
            sys.executable,
            str(SETUP_JETBRAINS_SCRIPT),
            "--editor",
            editor,
            "--token-file",
            str(token_path),
        ])
    elif editor == "vscode":
        result = run([
            sys.executable,
            str(SETUP_VSCODE_SCRIPT),
            "--token-file",
            str(token_path),
        ])
    else:
        raise ValueError(f"暂不支持通过 CLI 安装编辑器：{editor}")
    if result.stdout.strip():
        print(result.stdout.strip())
    write_editor(editor, config_path)
    return True


def choose_editor() -> str:
    options = [
        ("none", "基础模式（无需编辑器联动）"),
        ("goland", "GoLand 模式（语义引用与定位）"),
        ("idea", "IntelliJ IDEA 模式（语义引用与定位）"),
        ("vscode", "Visual Studio Code 模式（语义引用与定位）"),
    ]
    print("选择 Easy CR 代码编辑器能力：")
    for index, (_, label) in enumerate(options, start=1):
        print(f"  {index}. {label}")
    valid = {str(index): editor for index, (editor, _) in enumerate(options, start=1)}
    while True:
        choice = input(f"请输入 1 到 {len(options)}：").strip()
        if choice in valid:
            return valid[choice]
        print("请输入有效选项。")


def installed_jetbrains_plugin(editor: str) -> Path | None:
    descriptor = jetbrains_editor(editor)
    preferred = newest_plugins_dir(descriptor, descriptor.default_app) / "easy-cr"
    if preferred.is_dir():
        return preferred
    support_root = Path.home() / "Library" / "Application Support" / "JetBrains"
    candidates = sorted(
        support_root.glob(f"{descriptor.app_support_pattern}/plugins/easy-cr"),
        reverse=True,
    )
    return candidates[0] if candidates else None


def editor_setup_ready(
    editor: str,
    *,
    config_dir: Path = CONFIG_DIR,
) -> bool:
    """Whether the selected editor already has an adapter and valid token."""
    try:
        read_token(token_path_for_editor(editor, config_dir), editor)
    except ConfigError:
        return False
    if editor in JETBRAINS_EDITOR_IDS:
        return installed_jetbrains_plugin(editor) is not None
    if editor == "vscode":
        try:
            code_command = resolve_code_command()
        except RuntimeError:
            return False
        listed = run(
            [str(code_command), "--list-extensions"],
            allow_failure=True,
        )
        if listed.returncode:
            return False
        extension_ids = {
            line.strip().partition("@")[0].lower()
            for line in listed.stdout.splitlines()
        }
        return "bytedance.easy-cr" in extension_ids
    return False


def codex_installation_state(command: Path | None) -> dict[str, Any]:
    if command is None:
        return {"installed": False, "error": None}
    result = run([str(command), "plugin", "list"], allow_failure=True)
    return {
        "installed": result.returncode == 0 and "easy-cr@easy-cr" in result.stdout,
        "error": None if result.returncode == 0 else (
            result.stderr.strip() or result.stdout.strip() or "查询失败"
        ),
    }


def claude_installation_state(
    command: Path | None,
    repo_root: Path,
) -> dict[str, Any]:
    if command is None:
        return {
            "installed": False,
            "marketplaceSourceMatches": False,
            "error": None,
        }
    marketplace_result = run(
        [str(command), "plugin", "marketplace", "list", "--json"],
        allow_failure=True,
    )
    source_matches = False
    if marketplace_result.returncode == 0:
        try:
            marketplaces = json.loads(marketplace_result.stdout)
            for item in marketplaces:
                if not isinstance(item, dict) or item.get("name") != "easy-cr":
                    continue
                configured_path = item.get("path")
                if configured_path:
                    source_matches = (
                        Path(configured_path).expanduser().resolve()
                        == repo_root.resolve()
                    )
        except json.JSONDecodeError:
            pass
    list_result = run(
        [str(command), "plugin", "list", "--json"],
        allow_failure=True,
    )
    installed = False
    if list_result.returncode == 0:
        try:
            plugins = json.loads(list_result.stdout)
            installed = any(
                isinstance(item, dict) and item.get("id") == "easy-cr@easy-cr"
                for item in plugins
            )
        except json.JSONDecodeError:
            pass
    errors = [
        result.stderr.strip() or result.stdout.strip()
        for result in (marketplace_result, list_result)
        if result.returncode
    ]
    return {
        "installed": installed,
        "marketplaceSourceMatches": source_matches,
        "error": "; ".join(errors) or None,
    }


def check_editor_health(
    editor: str,
    *,
    token_path: Path | None = None,
    config_dir: Path = CONFIG_DIR,
) -> tuple[bool, str | None]:
    descriptor = editor_descriptor(editor)
    display = descriptor.display_name
    if descriptor.endpoint is None:
        return False, f"{display} 不提供运行时接口"
    resolved_token = token_path or token_path_for_editor(editor, config_dir)
    try:
        token = read_token(resolved_token, editor)
        request = urllib.request.Request(
            f"{descriptor.endpoint}/api/health",
            data=b"{}",
            method="POST",
            headers={
                "Content-Type": "application/json",
                "X-Easy-CR-Token": token,
            },
        )
        with urllib.request.urlopen(request, timeout=1.5) as response:
            payload = json.loads(response.read())
        if payload.get("ready") is not True:
            return False, f"{display} 扩展返回了无效状态"
        if payload.get("editor") != editor:
            return False, (
                f"运行中的扩展是 {payload.get('editor')!r}，"
                f"与当前配置 {editor!r} 不一致"
            )
        protocol = payload.get("protocolVersion")
        if protocol not in (PROTOCOL_VERSION, str(PROTOCOL_VERSION)):
            return False, (
                f"{display} 扩展协议版本不匹配："
                f"期望 {PROTOCOL_VERSION}，实际 {protocol!r}"
            )
        return True, None
    except urllib.error.HTTPError as error:
        if error.code == 404:
            return False, f"{display} 尚未加载新版 Easy CR 扩展，请重启 {display}"
        if error.code in (401, 403):
            return False, (
                f"{display} 扩展 token 校验失败，"
                f"请重新执行 easy-cr config editor {editor}"
            )
        return False, f"{display} 扩展返回 HTTP {error.code}"
    except ConfigError as error:
        return False, str(error)
    except (OSError, urllib.error.URLError, json.JSONDecodeError) as error:
        return False, str(error)


# Backward-compatible alias used by older tests and callers.
def check_goland_health(
    token_path: Path | None = None,
    endpoint: str | None = None,
) -> tuple[bool, str | None]:
    del endpoint  # endpoint is fixed by the editor registry
    return check_editor_health(
        "goland",
        token_path=token_path,
        config_dir=(token_path.parent if token_path is not None else CONFIG_DIR),
    )


def editor_runtime_status(
    editor: str,
    *,
    config_dir: Path,
    token_path: Path | None = None,
) -> dict[str, Any]:
    descriptor = editor_descriptor(editor)
    resolved_token = token_path or (
        token_path_for_editor(editor, config_dir)
        if descriptor.token_filename
        else None
    )
    token_exists = bool(resolved_token and resolved_token.expanduser().is_file())
    token_permission_ok = False
    if token_exists and resolved_token is not None:
        token_permission_ok = (
            stat.S_IMODE(resolved_token.expanduser().stat().st_mode) == 0o600
        )

    if editor in JETBRAINS_EDITOR_IDS:
        jb = jetbrains_editor(editor)
        plugin_path = installed_jetbrains_plugin(editor)
        runtime_ready, runtime_error = check_editor_health(
            editor,
            token_path=resolved_token,
            config_dir=config_dir,
        )
        return {
            "id": editor,
            "displayName": descriptor.display_name,
            "endpoint": descriptor.endpoint,
            "appInstalled": jb.default_app.is_dir(),
            "extensionInstalled": plugin_path is not None,
            "extensionPath": str(plugin_path) if plugin_path else None,
            "runtimeReady": runtime_ready,
            "runtimeError": runtime_error,
            "token": {
                "exists": token_exists,
                "permissionOk": token_permission_ok,
                "path": str(resolved_token) if resolved_token else None,
            },
        }

    if editor == "vscode":
        code_command: Path | None
        code_error: str | None = None
        try:
            code_command = resolve_code_command()
        except RuntimeError as error:
            code_command = None
            code_error = str(error)
        extension_installed = False
        extension_path = None
        if code_command is not None:
            listed = run([str(code_command), "--list-extensions"], allow_failure=True)
            if listed.returncode == 0 and "easy-cr" in listed.stdout.lower():
                extension_installed = True
                extension_path = "easy-cr"
        runtime_ready, runtime_error = check_editor_health(
            editor,
            token_path=resolved_token,
            config_dir=config_dir,
        )
        if code_error and not runtime_ready and runtime_error is None:
            runtime_error = code_error
        return {
            "id": editor,
            "displayName": descriptor.display_name,
            "endpoint": descriptor.endpoint,
            "appInstalled": VSCODE_APP.is_dir() or code_command is not None,
            "cliPath": str(code_command) if code_command else None,
            "extensionInstalled": extension_installed,
            "extensionPath": extension_path,
            "runtimeReady": runtime_ready,
            "runtimeError": runtime_error,
            "token": {
                "exists": token_exists,
                "permissionOk": token_permission_ok,
                "path": str(resolved_token) if resolved_token else None,
            },
        }

    return {
        "id": editor,
        "displayName": descriptor.display_name,
        "endpoint": descriptor.endpoint,
        "appInstalled": False,
        "extensionInstalled": False,
        "extensionPath": None,
        "runtimeReady": False,
        "runtimeError": f"{descriptor.display_name} 尚未实现安装诊断",
        "token": {
            "exists": token_exists,
            "permissionOk": token_permission_ok,
            "path": str(resolved_token) if resolved_token else None,
        },
    }


def collect_status(
    *,
    repo_root: Path = REPO_ROOT,
    home: Path = Path.home(),
    config_path: Path = CONFIG_PATH,
    token_path: Path | None = None,
    config_dir: Path | None = None,
    client_commands: dict[str, Path | None] | None = None,
) -> dict[str, Any]:
    commands = client_commands or detect_client_commands()
    cli_link = home / ".local" / "bin" / "easy-cr"
    expected_cli = repo_root / "bin" / "easy-cr"
    resolved_config_dir = config_dir or config_path.expanduser().parent
    try:
        editor = read_editor(config_path)
        editor_valid = True
        editor_error = None
    except ConfigError as error:
        editor = None
        editor_valid = False
        editor_error = str(error)

    runtime: dict[str, Any] | None = None
    # Preserve legacy goland block shape for compatibility.
    goland_block: dict[str, Any] = {
        "appInstalled": False,
        "extensionInstalled": False,
        "extensionPath": None,
        "runtimeReady": False,
        "runtimeError": None,
    }
    token_block = {"exists": False, "permissionOk": False}
    if editor in ENHANCED_EDITORS:
        runtime = editor_runtime_status(
            editor,
            config_dir=resolved_config_dir,
            token_path=(
                token_path
                if token_path is not None and editor == "goland"
                else None
            ),
        )
        token_block = {
            "exists": runtime["token"]["exists"],
            "permissionOk": runtime["token"]["permissionOk"],
        }
        if editor == "goland":
            goland_block = {
                "appInstalled": runtime["appInstalled"],
                "extensionInstalled": runtime["extensionInstalled"],
                "extensionPath": runtime["extensionPath"],
                "runtimeReady": runtime["runtimeReady"],
                "runtimeError": runtime["runtimeError"],
            }

    codex_source_matches = False
    codex_command = commands.get("codex")
    if codex_command is not None:
        configured_path = codex_marketplace_path(codex_command)
        if configured_path:
            codex_source_matches = (
                Path(configured_path).expanduser().resolve()
                == repo_root.resolve()
            )

    cli_target = cli_link.resolve(strict=False) if cli_link.is_symlink() else None
    codex_installation = codex_installation_state(commands.get("codex"))
    claude_installation = claude_installation_state(
        commands.get("claude"),
        repo_root,
    )
    helper_token_exists = MASTER_TOKEN_PATH.is_file()
    helper_token_permission_ok = False
    helper_runtime_ready = False
    if helper_token_exists:
        helper_token_permission_ok = (
            stat.S_IMODE(MASTER_TOKEN_PATH.stat().st_mode) == 0o600
        )
        try:
            helper_runtime_ready = helper_health(
                MASTER_TOKEN_PATH.read_text().strip(),
            )
        except OSError:
            helper_runtime_ready = False
    return {
        "source": str(repo_root.resolve()),
        "cli": {
            "path": str(cli_link),
            "installed": cli_link.is_symlink(),
            "sourceMatches": cli_target == expected_cli.resolve(),
        },
        "clients": {
            "codex": {
                "available": commands.get("codex") is not None,
                "command": str(commands["codex"]) if commands.get("codex") else None,
                "marketplaceSourceMatches": codex_source_matches,
                **codex_installation,
            },
            "claude": {
                "available": commands.get("claude") is not None,
                "command": str(commands["claude"]) if commands.get("claude") else None,
                **claude_installation,
            },
        },
        "editor": {
            "configured": editor,
            "valid": editor_valid,
            "error": editor_error,
            "protocolVersion": PROTOCOL_VERSION,
            "runtime": runtime,
        },
        "goland": goland_block,
        "token": token_block,
        "helper": {
            "endpoint": HELPER_ENDPOINT,
            "launchAgentInstalled": LAUNCH_AGENT_PATH.is_file(),
            "tokenExists": helper_token_exists,
            "tokenPermissionOk": helper_token_permission_ok,
            "runtimeReady": helper_runtime_ready,
        },
    }


def build_doctor_checks(payload: dict[str, Any]) -> list[dict[str, str]]:
    checks: list[dict[str, str]] = []

    def add(name: str, ok: bool, detail: str, *, warn: bool = False) -> None:
        checks.append({
            "name": name,
            "status": "pass" if ok else ("warn" if warn else "fail"),
            "detail": detail,
        })

    cli = payload["cli"]
    add("cli", cli["installed"] and cli["sourceMatches"], "全局命令软链")
    editor = payload["editor"]
    add("config", editor["valid"] and editor["configured"] is not None, "共享编辑器配置")
    clients = payload["clients"]
    available_clients = [
        name for name, state in clients.items() if state.get("available")
    ]
    add(
        "clients",
        bool(available_clients),
        "已检测：" + (", ".join(available_clients) or "无"),
        warn=True,
    )
    if clients["codex"]["available"]:
        add(
            "codex-marketplace",
            clients["codex"]["marketplaceSourceMatches"],
            "Easy CR marketplace 源码路径",
        )
        add(
            "codex-plugin",
            clients["codex"]["installed"],
            clients["codex"].get("error") or "Easy CR 插件安装状态",
        )
    if clients["claude"]["available"]:
        add(
            "claude-marketplace",
            clients["claude"]["marketplaceSourceMatches"],
            "Easy CR marketplace 源码路径",
        )
        add(
            "claude-plugin",
            clients["claude"]["installed"],
            clients["claude"].get("error") or "Easy CR 插件安装状态",
        )

    configured = editor["configured"]
    if configured in ENHANCED_EDITORS:
        runtime = editor.get("runtime") or {}
        token = runtime.get("token") or payload.get("token", {})
        display = runtime.get("displayName") or configured
        add(
            "token",
            token.get("exists", False) and token.get("permissionOk", False),
            "本机 token 存在且权限为 0600",
        )
        if configured in JETBRAINS_EDITOR_IDS or configured == "vscode":
            add(f"{configured}-app", bool(runtime.get("appInstalled")), f"{display} 应用")
            add(
                f"{configured}-extension",
                bool(runtime.get("extensionInstalled")),
                "Easy CR 扩展文件",
            )
        add(
            f"{configured}-runtime",
            bool(runtime.get("runtimeReady")),
            runtime.get("runtimeError") or "运行时接口可用",
        )
    helper = payload.get("helper", {})
    add(
        "helper-launch-agent",
        helper.get("launchAgentInstalled", False),
        "单实例常驻服务已注册",
    )
    add(
        "helper-token",
        helper.get("tokenExists", False)
        and helper.get("tokenPermissionOk", False),
        "helper token 存在且权限为 0600",
    )
    add(
        "helper-runtime",
        helper.get("runtimeReady", False),
        f"{HELPER_ENDPOINT.replace('http://', '')} 可用",
    )
    return checks


def print_status(payload: dict[str, Any]) -> None:
    print(f"源码：{payload['source']}")
    cli = payload["cli"]
    print(
        "CLI："
        + ("已安装" if cli["installed"] and cli["sourceMatches"] else "未正确安装")
    )
    for name, state in payload["clients"].items():
        if not state["available"]:
            label = "未检测到"
        elif state.get("installed"):
            label = "已安装 Easy CR"
        else:
            label = "已检测，未安装 Easy CR"
        print(f"{name.capitalize()}：{label}")
    editor = payload["editor"]["configured"] or "未配置"
    print(f"编辑器：{editor}")
    runtime = payload["editor"].get("runtime")
    if runtime:
        display = runtime.get("displayName") or editor
        print(
            f"{display} 扩展："
            + ("运行中" if runtime.get("runtimeReady") else "尚未加载")
        )
    helper = payload.get("helper", {})
    print(
        "评论服务："
        + ("运行中" if helper.get("runtimeReady") else "尚未运行")
    )


def handle_init(args: argparse.Namespace) -> int:
    commands = detect_client_commands()
    requested = list(dict.fromkeys(args.client))
    clients = requested or [
        name for name, command in commands.items() if command is not None
    ]
    if requested:
        missing = [name for name in requested if commands[name] is None]
        if missing:
            raise RuntimeError("未检测到客户端：" + ", ".join(missing))
    if not clients:
        print("未检测到 Codex 或 Claude Code，已仅配置 Easy CR 本地能力。")

    install_cli()
    install_helper_service()
    print("Easy CR 评论服务已启动。")
    for client in clients:
        command = commands[client]
        assert command is not None
        if client == "codex":
            configure_codex(command, REPO_ROOT, Path.home())
        else:
            configure_claude(command, REPO_ROOT)
        print(f"已配置 {client}")

    editor = args.editor or choose_editor()
    installed = configure_editor(editor)
    if editor == "none":
        print("Easy CR 已使用基础模式。")
    else:
        display = editor_descriptor(editor).display_name
        if installed:
            print(
                f"{display} 扩展已安装。"
                f"若窗口已在运行，请 Reload/重启一次使扩展生效。"
            )
        else:
            print(f"已切换到 {display} 模式，现有扩展和 token 保持不变。")
    return 0


def handle_open(args: argparse.Namespace) -> int:
    editor = read_editor()
    if editor is None or editor == "none":
        raise RuntimeError("当前未配置增强编辑器，请先执行 easy-cr config editor <editor>")
    project = (args.project or Path.cwd()).expanduser().resolve()
    app = launch_editor(editor, project)
    display = editor_descriptor(editor).display_name
    print(f"已启动 {display}：{app}")
    print(f"项目：{project}")
    print("若扩展刚安装，请等待加载完成后使用语义引用。")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        if args.command == "init":
            return handle_init(args)
        if args.command == "config":
            installed = configure_editor(args.editor)
            if args.editor == "none":
                print("已切换为基础模式。")
            else:
                display = editor_descriptor(args.editor).display_name
                if installed:
                    print(
                        f"已安装并启用 {display} 模式。"
                        f"若扩展未生效，请在 {display} 中 Reload Window 或重启一次。"
                    )
                else:
                    print(
                        f"已切换到 {display} 模式，"
                        "检测到现有扩展和 token，未重复安装。"
                    )
            return 0
        if args.command == "open":
            return handle_open(args)
        if args.command == "comments":
            source = args.report.read_text()
            payload = extract_comments(source)
            if args.resolve_batch:
                payload = mark_batch_resolved(
                    payload,
                    args.resolve_batch,
                    args.reply,
                )
                atomic_write_text(
                    args.report,
                    replace_comments_block(source, payload),
                )
            if args.json:
                print(json.dumps(payload, ensure_ascii=False, indent=2))
            else:
                print(comments_markdown(payload, args.report.stem))
            return 0
        payload = collect_status()
        if args.command == "status":
            if args.json:
                print(json.dumps(payload, ensure_ascii=False, indent=2))
            else:
                print_status(payload)
            return 0
        if (
            args.command == "doctor"
            and getattr(args, "launch", False)
            and payload["editor"].get("configured") in ENHANCED_EDITORS
            and not (payload["editor"].get("runtime") or {}).get("runtimeReady")
        ):
            editor = payload["editor"]["configured"]
            try:
                app = launch_editor(editor, Path.cwd())
                print(f"runtime 未就绪，已尝试启动 {editor_descriptor(editor).display_name}：{app}")
            except RuntimeError as error:
                print(f"runtime 未就绪，自动启动失败：{error}")
            payload = collect_status()
        checks = build_doctor_checks(payload)
        result = {
            "ok": not any(item["status"] == "fail" for item in checks),
            "checks": checks,
        }
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            labels = {"pass": "通过", "warn": "提醒", "fail": "失败"}
            for item in checks:
                print(f"[{labels[item['status']]}] {item['name']}：{item['detail']}")
        return 0 if result["ok"] else 1
    except (OSError, RuntimeError, ValueError) as error:
        print(f"easy-cr: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
