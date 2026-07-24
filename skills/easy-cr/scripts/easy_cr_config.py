#!/usr/bin/env python3
"""Shared Easy CR editor configuration."""

from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any


CONFIG_DIR = Path.home() / ".config" / "easy-cr"
CONFIG_PATH = CONFIG_DIR / "config.json"
TOKEN_PATH = CONFIG_DIR / "goland-token"
GOLAND_ENDPOINT = "http://127.0.0.1:64343"
VALID_EDITORS = frozenset({"none", "goland"})
TOKEN_PATTERN = re.compile(r"[A-Za-z0-9_-]{32,}")


class ConfigError(ValueError):
    """Configuration exists but is invalid."""


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
        raise ConfigError("Easy CR 配置无效：editor 仅支持 none 或 goland")
    return editor


def write_editor(editor: str, path: Path = CONFIG_PATH) -> Path:
    if editor not in VALID_EDITORS:
        raise ValueError("editor 仅支持 none 或 goland")
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


def read_token(path: Path = TOKEN_PATH) -> str:
    try:
        token = path.expanduser().read_text().strip()
    except FileNotFoundError as error:
        raise ConfigError("GoLand 扩展尚未安装或 token 缺失") from error
    except OSError as error:
        raise ConfigError(f"读取 GoLand token 失败：{error}") from error
    if not TOKEN_PATTERN.fullmatch(token):
        raise ConfigError("GoLand token 格式无效，请重新配置编辑器")
    return token


def resolve_semantic(
    config_path: Path = CONFIG_PATH,
    token_path: Path = TOKEN_PATH,
) -> tuple[dict[str, str], str | None]:
    try:
        editor = read_editor(config_path)
    except ConfigError as error:
        return {"mode": "none"}, str(error)
    if editor is None:
        return {"mode": "none"}, "Easy CR 尚未配置代码编辑器"
    if editor == "none":
        return {"mode": "none"}, None
    if editor == "goland":
        try:
            token = read_token(token_path)
        except ConfigError as error:
            return {"mode": "none"}, f"GoLand 增强不可用：{error}"
        return {
            "mode": "goland",
            "endpoint": GOLAND_ENDPOINT,
            "token": token,
        }, None
    raise AssertionError(f"unhandled editor: {editor}")
