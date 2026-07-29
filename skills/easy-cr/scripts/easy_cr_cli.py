#!/usr/bin/env python3
"""Initialize and diagnose Easy CR for Codex, Claude Code, and GoLand."""

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
    CONFIG_PATH,
    GOLAND_ENDPOINT,
    TOKEN_PATH,
    ConfigError,
    read_editor,
    read_token,
    write_editor,
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


VERSION = "1.4.0"
SKILL_DIR = SCRIPT_DIR.parent
REPO_ROOT = SKILL_DIR.parents[1]
SETUP_GOLAND_SCRIPT = SCRIPT_DIR / "setup_goland_plugin.py"
INSTALL_CLI_SCRIPT = REPO_ROOT / "scripts" / "install_cli.py"
CODEX_APP_COMMAND = Path("/Applications/ChatGPT.app/Contents/Resources/codex")
GOLAND_APP = Path("/Applications/GoLand.app")
GOLAND_PLUGIN_ROOT = (
    Path.home() / "Library" / "Application Support" / "JetBrains"
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="easy-cr", description=__doc__)
    parser.add_argument("--version", action="version", version=f"easy-cr {VERSION}")
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser("init", help="配置已安装客户端和编辑器")
    init_parser.add_argument("--editor", choices=("none", "goland"))
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
    editor_parser.add_argument("editor", choices=("none", "goland"))

    doctor_parser = subparsers.add_parser("doctor", help="诊断本地安装")
    doctor_parser.add_argument("--json", action="store_true")

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


def marketplace_source_path(repo_root: Path, home: Path) -> str:
    repo_root = repo_root.resolve()
    home = home.expanduser().resolve()
    try:
        relative = repo_root.relative_to(home)
        return f"./{relative.as_posix()}"
    except ValueError:
        return str(repo_root)


def upsert_codex_marketplace(
    repo_root: Path,
    marketplace_path: Path,
    home: Path,
) -> bool:
    try:
        payload = json.loads(marketplace_path.read_text())
    except FileNotFoundError:
        payload = {
            "name": "personal",
            "interface": {"displayName": "Personal"},
            "plugins": [],
        }
    except (OSError, json.JSONDecodeError) as error:
        raise RuntimeError(f"读取 Codex marketplace 失败：{error}") from error
    if not isinstance(payload, dict):
        raise RuntimeError("Codex marketplace 顶层必须为 JSON 对象")
    plugins = payload.setdefault("plugins", [])
    if not isinstance(plugins, list):
        raise RuntimeError("Codex marketplace plugins 必须为数组")

    desired = {
        "name": "easy-cr",
        "source": {
            "source": "local",
            "path": marketplace_source_path(repo_root, home),
        },
        "policy": {
            "installation": "AVAILABLE",
            "authentication": "ON_INSTALL",
        },
        "category": "Productivity",
    }
    existing = next(
        (item for item in plugins if isinstance(item, dict) and item.get("name") == "easy-cr"),
        None,
    )
    if existing == desired:
        return False
    if existing is None:
        plugins.append(desired)
    else:
        existing.clear()
        existing.update(desired)
    atomic_write_json(marketplace_path, payload)
    return True


def run(command: list[str], *, allow_failure: bool = False) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(command, text=True, capture_output=True, check=False)
    if result.returncode and not allow_failure:
        detail = result.stderr.strip() or result.stdout.strip() or "命令执行失败"
        raise RuntimeError(f"{' '.join(command)}: {detail}")
    return result


def configure_codex(command: Path, repo_root: Path, home: Path) -> None:
    marketplace = home / ".agents" / "plugins" / "marketplace.json"
    upsert_codex_marketplace(repo_root, marketplace, home)
    run([str(command), "plugin", "add", "easy-cr@personal"])


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
    token_path: Path = TOKEN_PATH,
) -> None:
    if editor == "none":
        write_editor("none", config_path)
        return
    result = run([
        sys.executable,
        str(SETUP_GOLAND_SCRIPT),
        "--token-file",
        str(token_path),
    ])
    if result.stdout.strip():
        print(result.stdout.strip())
    write_editor("goland", config_path)


def choose_editor() -> str:
    print("选择 Easy CR 代码编辑器能力：")
    print("  1. 基础模式（无需编辑器联动）")
    print("  2. GoLand 模式（支持代码引用与定位）")
    while True:
        choice = input("请输入 1 或 2：").strip()
        if choice == "1":
            return "none"
        if choice == "2":
            return "goland"
        print("请输入有效选项。")


def installed_goland_plugin() -> Path | None:
    candidates = sorted(
        GOLAND_PLUGIN_ROOT.glob("GoLand*/plugins/easy-cr"),
        reverse=True,
    )
    return candidates[0] if candidates else None


def codex_installation_state(command: Path | None) -> dict[str, Any]:
    if command is None:
        return {"installed": False, "error": None}
    result = run([str(command), "plugin", "list"], allow_failure=True)
    return {
        "installed": result.returncode == 0 and "easy-cr@personal" in result.stdout,
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


def check_goland_health(
    token_path: Path = TOKEN_PATH,
    endpoint: str = GOLAND_ENDPOINT,
) -> tuple[bool, str | None]:
    try:
        token = read_token(token_path)
        request = urllib.request.Request(
            f"{endpoint}/api/health",
            data=b"{}",
            method="POST",
            headers={
                "Content-Type": "application/json",
                "X-Easy-CR-Token": token,
            },
        )
        with urllib.request.urlopen(request, timeout=1.5) as response:
            payload = json.loads(response.read())
        if payload.get("ready") is True:
            return True, None
        return False, "GoLand 扩展返回了无效状态"
    except urllib.error.HTTPError as error:
        if error.code == 404:
            return False, "GoLand 尚未加载新版 Easy CR 扩展，请重启 GoLand"
        if error.code in (401, 403):
            return False, "GoLand 扩展 token 校验失败，请重新执行 easy-cr config editor goland"
        return False, f"GoLand 扩展返回 HTTP {error.code}"
    except ConfigError as error:
        return False, str(error)
    except (OSError, urllib.error.URLError, json.JSONDecodeError) as error:
        return False, str(error)


def collect_status(
    *,
    repo_root: Path = REPO_ROOT,
    home: Path = Path.home(),
    config_path: Path = CONFIG_PATH,
    token_path: Path = TOKEN_PATH,
    client_commands: dict[str, Path | None] | None = None,
) -> dict[str, Any]:
    commands = client_commands or detect_client_commands()
    cli_link = home / ".local" / "bin" / "easy-cr"
    expected_cli = repo_root / "bin" / "easy-cr"
    try:
        editor = read_editor(config_path)
        editor_valid = True
        editor_error = None
    except ConfigError as error:
        editor = None
        editor_valid = False
        editor_error = str(error)

    runtime_ready = False
    runtime_error = None
    if editor == "goland":
        runtime_ready, runtime_error = check_goland_health(token_path)

    codex_marketplace = home / ".agents" / "plugins" / "marketplace.json"
    codex_source_matches = False
    try:
        codex_payload = json.loads(codex_marketplace.read_text())
        desired_path = marketplace_source_path(repo_root, home)
        codex_source_matches = any(
            item.get("name") == "easy-cr"
            and item.get("source", {}).get("path") == desired_path
            for item in codex_payload.get("plugins", [])
            if isinstance(item, dict)
        )
    except (OSError, json.JSONDecodeError, AttributeError):
        pass

    cli_target = cli_link.resolve(strict=False) if cli_link.is_symlink() else None
    plugin_path = installed_goland_plugin()
    codex_installation = codex_installation_state(commands.get("codex"))
    claude_installation = claude_installation_state(
        commands.get("claude"),
        repo_root,
    )
    token_exists = token_path.expanduser().is_file()
    token_permission_ok = False
    if token_exists:
        token_permission_ok = (
            stat.S_IMODE(token_path.expanduser().stat().st_mode) == 0o600
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
        },
        "goland": {
            "appInstalled": GOLAND_APP.is_dir(),
            "extensionInstalled": plugin_path is not None,
            "extensionPath": str(plugin_path) if plugin_path else None,
            "runtimeReady": runtime_ready,
            "runtimeError": runtime_error,
        },
        "token": {
            "exists": token_exists,
            "permissionOk": token_permission_ok,
        },
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
            "personal marketplace 源码路径",
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
    if editor["configured"] == "goland":
        goland = payload["goland"]
        token = payload.get("token", {})
        add(
            "token",
            token.get("exists", False) and token.get("permissionOk", False),
            "本机 token 存在且权限为 0600",
        )
        add("goland-app", goland["appInstalled"], "GoLand 应用")
        add("goland-extension", goland["extensionInstalled"], "Easy CR 扩展文件")
        add(
            "goland-runtime",
            goland["runtimeReady"],
            goland["runtimeError"] or "运行时接口可用",
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
        "127.0.0.1:64344 可用",
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
    if editor == "goland":
        print(
            "GoLand 扩展："
            + ("运行中" if payload["goland"]["runtimeReady"] else "尚未加载")
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
    configure_editor(editor)
    if editor == "goland":
        print("GoLand 扩展已安装，请手动重启 GoLand 后使用语义引用。")
    else:
        print("Easy CR 已使用基础模式。")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        if args.command == "init":
            return handle_init(args)
        if args.command == "config":
            configure_editor(args.editor)
            if args.editor == "goland":
                print("已启用 GoLand 模式，请手动重启 GoLand 使扩展生效。")
            else:
                print("已切换为基础模式。")
            return 0
        if args.command == "comments":
            source = args.report.read_text()
            payload = extract_comments(source)
            if args.resolve_batch:
                payload = mark_batch_resolved(payload, args.resolve_batch)
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
