#!/usr/bin/env python3
"""Shared Easy CR editor configuration."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any


CONFIG_DIR = Path.home() / ".config" / "easy-cr"
CONFIG_PATH = CONFIG_DIR / "config.json"
TOKEN_PATH = CONFIG_DIR / "goland-token"
GOLAND_ENDPOINT = "http://127.0.0.1:64343"
TOKEN_PATTERN = re.compile(r"[A-Za-z0-9_-]{32,}")
PROTOCOL_VERSION = 2


@dataclass(frozen=True)
class EditorDescriptor:
    """Immutable built-in editor endpoint description."""

    editor_id: str
    display_name: str
    endpoint: str | None
    token_filename: str | None
    # macOS .app bundle name used with `open -a`.
    app_name: str | None = None
    # Browser-openable URL scheme prefix for best-effort launch from HTML.
    # {repo} is replaced with the absolute repository path.
    launch_uri_template: str | None = None


EDITOR_DESCRIPTORS: dict[str, EditorDescriptor] = {
    "none": EditorDescriptor("none", "基础模式", None, None),
    "goland": EditorDescriptor(
        "goland",
        "GoLand",
        "http://127.0.0.1:64343",
        "goland-token",
        app_name="GoLand",
        # JetBrains Toolbox protocol; opens/focuses GoLand when registered.
        launch_uri_template="jetbrains://goland/navigate/reference?project={project}&path=.gitignore:1:1",
    ),
    "idea": EditorDescriptor(
        "idea",
        "IntelliJ IDEA",
        "http://127.0.0.1:64344",
        "idea-token",
        app_name="IntelliJ IDEA",
        launch_uri_template="jetbrains://idea/navigate/reference?project={project}&path=.gitignore:1:1",
    ),
    "vscode": EditorDescriptor(
        "vscode",
        "Visual Studio Code",
        "http://127.0.0.1:64345",
        "vscode-token",
        app_name="Visual Studio Code",
        launch_uri_template="vscode://file{repo}",
    ),
}
VALID_EDITORS = frozenset(EDITOR_DESCRIPTORS)
ENHANCED_EDITORS = frozenset(
    editor for editor in VALID_EDITORS if editor != "none"
)


class ConfigError(ValueError):
    """Configuration exists but is invalid."""


def editor_descriptor(editor: str) -> EditorDescriptor:
    try:
        return EDITOR_DESCRIPTORS[editor]
    except KeyError as error:
        raise ValueError(
            "editor 仅支持 " + "、".join(sorted(VALID_EDITORS))
        ) from error


def token_path_for_editor(
    editor: str,
    config_dir: Path = CONFIG_DIR,
) -> Path:
    descriptor = editor_descriptor(editor)
    if descriptor.token_filename is None:
        raise ValueError(f"{editor} 不使用本机 token")
    return config_dir.expanduser() / descriptor.token_filename


def read_editor(path: Path = CONFIG_PATH) -> str | None:
    try:
        payload: Any = json.loads(path.expanduser().read_text())
    except FileNotFoundError:
        return None
    except (OSError, json.JSONDecodeError) as error:
        raise ConfigError(f"Easy CR 配置无效：{error}") from error
    if not isinstance(payload, dict) or payload.get("version") != 1:
        raise ConfigError("Easy CR 配置无效：version 必须为 1")
    editor = payload.get("editor")
    if editor not in VALID_EDITORS:
        raise ConfigError(
            "Easy CR 配置无效：editor 仅支持 "
            + "、".join(sorted(VALID_EDITORS))
        )
    return editor


def write_editor(editor: str, path: Path = CONFIG_PATH) -> Path:
    editor_descriptor(editor)
    path = path.expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.parent.chmod(0o700)
    payload = json.dumps(
        {"version": 1, "editor": editor},
        ensure_ascii=False,
        indent=2,
    ) + "\n"
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=".config-",
        suffix=".json",
        dir=path.parent,
        text=True,
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w") as stream:
            stream.write(payload)
        temporary.chmod(0o600)
        os.replace(temporary, path)
        path.chmod(0o600)
    finally:
        temporary.unlink(missing_ok=True)
    return path


def read_token(path: Path = TOKEN_PATH, editor: str = "goland") -> str:
    display_name = editor_descriptor(editor).display_name
    try:
        token = path.expanduser().read_text().strip()
    except FileNotFoundError as error:
        raise ConfigError(f"{display_name} 扩展尚未安装或 token 缺失") from error
    except OSError as error:
        raise ConfigError(f"读取 {display_name} token 失败：{error}") from error
    if not TOKEN_PATTERN.fullmatch(token):
        raise ConfigError(f"{display_name} token 格式无效，请重新配置编辑器")
    return token


def launch_uri_for(editor: str, repo: str | Path | None = None) -> str | None:
    """Build a browser-openable launch URI for the editor, if supported."""
    descriptor = editor_descriptor(editor)
    template = descriptor.launch_uri_template
    if not template:
        return None
    repo_path = Path(repo or ".").expanduser().resolve()
    return (
        template
        .replace("{repo}", str(repo_path))
        .replace("{project}", repo_path.name)
    )


def launch_editor(
    editor: str,
    project_path: str | Path | None = None,
) -> Path:
    """Launch the configured macOS editor app, optionally opening a project.

    Returns the application path that was requested. Raises RuntimeError when
    the editor cannot be launched from this machine.
    """
    descriptor = editor_descriptor(editor)
    if descriptor.app_name is None:
        raise RuntimeError(f"{editor} 不支持自动启动")
    app = Path("/Applications") / f"{descriptor.app_name}.app"
    if not app.is_dir():
        raise RuntimeError(f"未找到应用：{app}")
    command = ["open", "-a", descriptor.app_name]
    if project_path is not None:
        project = Path(project_path).expanduser().resolve()
        command.append(str(project))
    # Prefer the discovered VS Code CLI when available so the workspace opens
    # in the same installation that hosts the Easy CR extension.
    if editor == "vscode":
        code = shutil.which("code")
        app_code = Path(
            "/Applications/Visual Studio Code.app/Contents/Resources/app/bin/code"
        )
        cli = Path(code) if code else (app_code if app_code.is_file() else None)
        if cli is not None:
            args = [str(cli)]
            if project_path is not None:
                args.extend(["-r", str(Path(project_path).expanduser().resolve())])
            else:
                args.append("-r")
            result = subprocess.run(args, text=True, capture_output=True, check=False)
            if result.returncode == 0:
                return app
    result = subprocess.run(command, text=True, capture_output=True, check=False)
    if result.returncode:
        detail = result.stderr.strip() or result.stdout.strip() or "open failed"
        raise RuntimeError(f"启动 {descriptor.display_name} 失败：{detail}")
    return app


def resolve_semantic(
    config_path: Path = CONFIG_PATH,
    token_path: Path | None = None,
    config_dir: Path | None = None,
    repo: str | Path | None = None,
) -> tuple[dict[str, str], str | None]:
    """Resolve the editor-neutral semantic payload for generated HTML.

    ``token_path`` is kept for backward compatibility with the legacy
    GoLand-only call signature. New callers should pass ``config_dir``.
    """
    try:
        editor = read_editor(config_path)
    except ConfigError as error:
        return {"mode": "none"}, str(error)
    if editor is None:
        return {"mode": "none"}, "Easy CR 尚未配置代码编辑器"
    if editor == "none":
        return {"mode": "none"}, None
    descriptor = editor_descriptor(editor)
    if config_dir is not None:
        resolved_token_path = token_path_for_editor(editor, config_dir)
    elif token_path is not None:
        resolved_token_path = token_path
    else:
        resolved_token_path = token_path_for_editor(
            editor,
            config_path.expanduser().parent,
        )
    try:
        token = read_token(resolved_token_path, editor)
    except ConfigError as error:
        return {"mode": "none"}, f"{descriptor.display_name} 增强不可用：{error}"
    payload = {
        "mode": "editor",
        "editor": descriptor.editor_id,
        "displayName": descriptor.display_name,
        "endpoint": descriptor.endpoint or "",
        "protocolVersion": str(PROTOCOL_VERSION),
        "token": token,
    }
    if descriptor.app_name:
        payload["appName"] = descriptor.app_name
    launch_uri = launch_uri_for(editor, repo)
    if launch_uri:
        payload["launchUri"] = launch_uri
    return payload, None
