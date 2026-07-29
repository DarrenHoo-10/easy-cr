#!/usr/bin/env python3
"""Single-instance Easy CR helper for report persistence and review completion."""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import plistlib
import secrets
import shutil
import socket
import stat
import struct
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from review_comments import extract_comments, replace_comments_block


HELPER_HOST = "127.0.0.1"
HELPER_PORT = 64344
HELPER_ENDPOINT = f"http://{HELPER_HOST}:{HELPER_PORT}"
HELPER_LABEL = "com.bytedance.easy-cr.helper"
CONFIG_DIR = Path.home() / ".config" / "easy-cr"
MASTER_TOKEN_PATH = CONFIG_DIR / "helper-token"
REGISTRY_PATH = CONFIG_DIR / "helper-reports.json"
LOG_DIR = CONFIG_DIR / "logs"
LAUNCH_AGENT_PATH = (
    Path.home()
    / "Library"
    / "LaunchAgents"
    / f"{HELPER_LABEL}.plist"
)
MAX_REQUEST_BYTES = 2 * 1024 * 1024
CODEX_APP_COMMAND = Path("/Applications/ChatGPT.app/Contents/Resources/codex")
CODEX_IPC_SOCKET = Path.home() / ".codex" / "ipc" / "ipc.sock"
CODEX_IPC_REQUEST_VERSION = 1
CODEX_IPC_TIMEOUT_SECONDS = 10.0


class ConflictError(ValueError):
    """The browser is trying to overwrite a newer report revision."""


def _atomic_write(path: Path, content: bytes, mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        dir=path.parent,
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.chmod(mode)
        os.replace(temporary, path)
        path.chmod(mode)
    finally:
        temporary.unlink(missing_ok=True)


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    _atomic_write(
        path,
        (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode(),
    )


def ensure_master_token(path: Path = MASTER_TOKEN_PATH) -> str:
    path = path.expanduser()
    try:
        token = path.read_text().strip()
        if len(token) < 32:
            raise ValueError("Easy CR helper token 格式无效")
        if stat.S_IMODE(path.stat().st_mode) != 0o600:
            path.chmod(0o600)
        return token
    except FileNotFoundError:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.parent.chmod(0o700)
        token = secrets.token_urlsafe(32)
        _atomic_write(path, (token + "\n").encode())
        return token


def launch_agent_payload(
    python: Path,
    helper_script: Path,
    token_path: Path,
    *,
    log_dir: Path = LOG_DIR,
) -> dict[str, Any]:
    return {
        "Label": HELPER_LABEL,
        "ProgramArguments": [
            str(python),
            str(helper_script),
            "serve",
            "--host",
            HELPER_HOST,
            "--port",
            str(HELPER_PORT),
            "--token-file",
            str(token_path),
        ],
        "RunAtLoad": True,
        "KeepAlive": True,
        "ProcessType": "Background",
        "StandardOutPath": str(log_dir / "helper.stdout.log"),
        "StandardErrorPath": str(log_dir / "helper.stderr.log"),
    }


def _run_launchctl(arguments: list[str], *, allow_failure: bool = False) -> None:
    result = subprocess.run(
        ["/bin/launchctl", *arguments],
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode and not allow_failure:
        detail = result.stderr.strip() or result.stdout.strip() or "launchctl 失败"
        raise RuntimeError(detail)


def _kickstart_helper(launch_agent_path: Path) -> None:
    domain = f"gui/{os.getuid()}"
    target = f"{domain}/{HELPER_LABEL}"
    try:
        _run_launchctl(["kickstart", "-k", target])
    except RuntimeError:
        _run_launchctl(["bootstrap", domain, str(launch_agent_path)])
        _run_launchctl(["kickstart", "-k", target])


def install_helper_service(
    *,
    launch_agent_path: Path = LAUNCH_AGENT_PATH,
    token_path: Path = MASTER_TOKEN_PATH,
    python: Path = Path(sys.executable),
    helper_script: Path = Path(__file__).resolve(),
) -> Path:
    ensure_master_token(token_path)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    payload = launch_agent_payload(python, helper_script, token_path)
    serialized = plistlib.dumps(payload, fmt=plistlib.FMT_XML)
    current = launch_agent_path.read_bytes() if launch_agent_path.is_file() else None
    if current != serialized:
        _atomic_write(launch_agent_path, serialized, mode=0o644)
        domain = f"gui/{os.getuid()}"
        _run_launchctl(["bootout", f"{domain}/{HELPER_LABEL}"], allow_failure=True)
        _run_launchctl(["bootstrap", domain, str(launch_agent_path)])
    _kickstart_helper(launch_agent_path)
    return launch_agent_path


def helper_health(
    token: str,
    endpoint: str = HELPER_ENDPOINT,
    *,
    timeout: float = 1.0,
) -> bool:
    try:
        payload = _post_json(
            endpoint,
            "/api/health",
            token,
            {},
            timeout=timeout,
        )
        return payload.get("ready") is True
    except (OSError, RuntimeError, urllib.error.URLError):
        return False


def ensure_helper_running(
    *,
    token_path: Path = MASTER_TOKEN_PATH,
    launch_agent_path: Path = LAUNCH_AGENT_PATH,
    endpoint: str = HELPER_ENDPOINT,
) -> str:
    token = ensure_master_token(token_path)
    if helper_health(token, endpoint):
        return token
    if not launch_agent_path.is_file():
        install_helper_service(
            launch_agent_path=launch_agent_path,
            token_path=token_path,
        )
    else:
        _kickstart_helper(launch_agent_path)
    for _ in range(20):
        if helper_health(token, endpoint, timeout=0.5):
            return token
        time.sleep(0.1)
    raise RuntimeError("Easy CR helper 未能启动，请运行 easy-cr doctor")


def _post_json(
    endpoint: str,
    path: str,
    token: str,
    payload: dict[str, Any],
    *,
    timeout: float = 2.0,
) -> dict[str, Any]:
    request = urllib.request.Request(
        endpoint + path,
        data=json.dumps(payload, ensure_ascii=False).encode(),
        method="POST",
        headers={
            "Content-Type": "application/json",
            "X-Easy-CR-Token": token,
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            result = json.loads(response.read())
    except urllib.error.HTTPError as error:
        try:
            detail = json.loads(error.read()).get("error")
        except (json.JSONDecodeError, AttributeError):
            detail = None
        raise RuntimeError(detail or f"Easy CR helper HTTP {error.code}") from error
    if not isinstance(result, dict):
        raise RuntimeError("Easy CR helper 返回了无效数据")
    return result


def detect_originating_agent(environ: dict[str, str] | None = None) -> dict[str, str] | None:
    values = environ or os.environ
    codex_session = values.get("CODEX_THREAD_ID")
    if codex_session:
        return {
            "client": "codex",
            "sessionId": codex_session,
            "cwd": str(Path.cwd().resolve()),
        }
    claude_session = (
        values.get("CLAUDE_CODE_SESSION_ID")
        or values.get("CLAUDE_SESSION_ID")
    )
    if claude_session:
        return {
            "client": "claude",
            "sessionId": claude_session,
            "cwd": str(Path.cwd().resolve()),
        }
    return None


def prepare_report_helper(
    report_id: str,
    report_path: Path,
    repository_roots: list[Path],
    *,
    report_subject: str | None = None,
    endpoint: str = HELPER_ENDPOINT,
    token_path: Path = MASTER_TOKEN_PATH,
) -> dict[str, Any]:
    report_path = report_path.expanduser().resolve()
    if report_path.suffix.lower() not in {".html", ".htm"}:
        raise ValueError("Easy CR helper 只支持 HTML 报告")
    if ".codex-artifacts" not in report_path.parts:
        raise ValueError("报告必须位于仓库的 .codex-artifacts 目录")
    master_token = ensure_helper_running(token_path=token_path, endpoint=endpoint)
    roots = [root.expanduser().resolve() for root in repository_roots]
    agent = detect_originating_agent()
    if agent is not None:
        cwd = Path(agent["cwd"]).resolve()
        if not any(cwd == root or root in cwd.parents for root in roots):
            agent["cwd"] = str(roots[0])
    result = _post_json(
        endpoint,
        "/api/reports/register",
        master_token,
        {
            "reportId": report_id,
            "path": str(report_path),
            "repositoryRoots": [str(root) for root in roots],
            "agent": agent,
            "subject": report_subject,
        },
    )
    return {
        "mode": "local",
        "endpoint": endpoint,
        "token": result["reportToken"],
        "agentBound": result.get("agentBound", False),
    }


def agent_prompt(
    agent: dict[str, Any],
    report_path: Path,
) -> str:
    report_subject = str(agent.get("reportSubject") or report_path.stem)
    batch_id = agent.get("reviewBatchId")
    comment_ids = agent.get("reviewCommentIds")
    if (
        isinstance(batch_id, str)
        and batch_id
        and isinstance(comment_ids, list)
        and comment_ids
    ):
        return (
            f"我已完成 CR，请处理「{report_subject}」CR 报告中本次发送的 "
            f"{len(comment_ids)} 条评论（批次 {batch_id}）：{report_path}"
        )
    return f"我已完成 CR，请处理「{report_subject}」CR 报告的评论：{report_path}"


def agent_command(
    agent: dict[str, Any],
    report_path: Path,
    *,
    codex_command: Path | None = None,
    claude_command: Path | None = None,
) -> list[str]:
    client = agent.get("client")
    session_id = agent.get("sessionId")
    prompt = agent_prompt(agent, report_path)
    if client == "codex":
        detected = shutil.which("codex")
        executable = codex_command or (
            Path(detected) if detected else CODEX_APP_COMMAND
        )
        return [str(executable), "exec", "resume", str(session_id), prompt]
    elif client == "claude":
        detected = shutil.which("claude")
        executable = claude_command or (Path(detected) if detected else None)
        if executable is None:
            raise RuntimeError("未找到 Claude Code CLI")
        return [
            str(executable),
            "--resume",
            str(session_id),
            "--print",
            prompt,
        ]
    raise RuntimeError("报告未绑定可恢复的 Agent")


def _write_ipc_frame(connection: socket.socket, payload: dict[str, Any]) -> None:
    encoded = json.dumps(payload, ensure_ascii=False).encode()
    connection.sendall(struct.pack("<I", len(encoded)) + encoded)


def _read_ipc_exact(connection: socket.socket, size: int) -> bytes:
    chunks: list[bytes] = []
    remaining = size
    while remaining:
        chunk = connection.recv(remaining)
        if not chunk:
            raise RuntimeError("Codex Desktop IPC 连接已关闭")
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def _read_ipc_frame(connection: socket.socket) -> dict[str, Any]:
    size = struct.unpack("<I", _read_ipc_exact(connection, 4))[0]
    if size <= 0 or size > MAX_REQUEST_BYTES:
        raise RuntimeError("Codex Desktop IPC 返回了无效消息")
    payload = json.loads(_read_ipc_exact(connection, size))
    if not isinstance(payload, dict):
        raise RuntimeError("Codex Desktop IPC 返回格式无效")
    return payload


def _wait_ipc_response(
    connection: socket.socket,
    request_id: str,
) -> dict[str, Any]:
    while True:
        payload = _read_ipc_frame(connection)
        if payload.get("type") == "client-discovery-request":
            _write_ipc_frame(
                connection,
                {
                    "type": "client-discovery-response",
                    "requestId": payload.get("requestId"),
                    "response": {"canHandle": False},
                },
            )
            continue
        if payload.get("type") != "response" or payload.get("requestId") != request_id:
            continue
        if payload.get("resultType") != "success":
            raise RuntimeError(
                f"Codex Desktop 未接收当前会话消息：{payload.get('error') or 'unknown-error'}"
            )
        return payload


def submit_codex_turn(
    session_id: str,
    prompt: str,
    *,
    socket_path: Path = CODEX_IPC_SOCKET,
    timeout_seconds: float = CODEX_IPC_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    try:
        conversation_id = str(uuid.UUID(str(session_id)))
    except (ValueError, AttributeError, TypeError) as error:
        raise ValueError("Codex sessionId 不是有效 UUID") from error
    socket_path = socket_path.expanduser()
    if not socket_path.is_socket():
        raise RuntimeError("Codex Desktop IPC 不可用，请先打开绑定报告的 Codex 会话")
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
            connection.settimeout(timeout_seconds)
            connection.connect(str(socket_path))
            initialize_id = str(uuid.uuid4())
            _write_ipc_frame(
                connection,
                {
                    "type": "request",
                    "requestId": initialize_id,
                    "method": "initialize",
                    "params": {"clientType": "easy-cr"},
                },
            )
            initialized = _wait_ipc_response(connection, initialize_id)
            client_id = str(
                (initialized.get("result") or {}).get("clientId") or ""
            )
            if not client_id:
                raise RuntimeError("Codex Desktop IPC 初始化失败")
            request_id = str(uuid.uuid4())
            _write_ipc_frame(
                connection,
                {
                    "type": "request",
                    "requestId": request_id,
                    "sourceClientId": client_id,
                    "version": CODEX_IPC_REQUEST_VERSION,
                    "method": "thread-follower-start-turn",
                    "params": {
                        "conversationId": conversation_id,
                        "turnStartParams": {
                            "input": [{"type": "text", "text": prompt}],
                            "clientUserMessageId": str(uuid.uuid4()),
                        },
                    },
                    "timeoutMs": int(timeout_seconds * 1000),
                },
            )
            return _wait_ipc_response(connection, request_id)
    except (OSError, socket.timeout) as error:
        raise RuntimeError(f"Codex Desktop 当前会话提交失败：{error}") from error


def codex_thread_url(session_id: str) -> str:
    try:
        normalized = str(uuid.UUID(str(session_id)))
    except (ValueError, AttributeError, TypeError) as error:
        raise ValueError("Codex sessionId 不是有效 UUID") from error
    return f"codex://threads/{normalized}"


def _default_client_opener(agent: dict[str, Any]) -> bool:
    if agent.get("client") != "codex":
        return False
    target = codex_thread_url(str(agent.get("sessionId") or ""))
    result = subprocess.run(
        ["/usr/bin/open", target],
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode:
        detail = result.stderr.strip() or result.stdout.strip() or "无法打开 Codex 原任务"
        raise RuntimeError(detail)
    return True


def _default_launcher(agent: dict[str, Any], report_path: Path) -> None:
    if agent.get("client") == "codex":
        submit_codex_turn(
            str(agent.get("sessionId") or ""),
            agent_prompt(agent, report_path),
        )
        return
    cwd = Path(str(agent.get("cwd") or report_path.parent)).resolve()
    arguments = agent_command(agent, report_path)
    if not Path(arguments[0]).is_file():
        raise RuntimeError(f"未找到 Agent CLI：{arguments[0]}")
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_name = hashlib.sha256(str(report_path).encode()).hexdigest()[:12]
    log = (LOG_DIR / f"review-{log_name}.log").open("ab")
    try:
        subprocess.Popen(
            arguments,
            cwd=cwd,
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    finally:
        log.close()


class HelperStore:
    def __init__(
        self,
        config_dir: Path = CONFIG_DIR,
        *,
        launcher: Callable[[dict[str, Any], Path], None] = _default_launcher,
        client_opener: Callable[[dict[str, Any]], bool] = _default_client_opener,
    ) -> None:
        self.config_dir = config_dir.expanduser()
        self.registry_path = self.config_dir / "helper-reports.json"
        self.launcher = launcher
        self.client_opener = client_opener
        self.lock = threading.RLock()
        self.config_dir.mkdir(parents=True, exist_ok=True)
        self.config_dir.chmod(0o700)

    def _load(self) -> dict[str, Any]:
        try:
            payload = json.loads(self.registry_path.read_text())
        except FileNotFoundError:
            return {"version": 1, "reports": {}}
        if not isinstance(payload, dict) or not isinstance(payload.get("reports"), dict):
            raise ValueError("Easy CR helper registry 无效")
        return payload

    def _save(self, payload: dict[str, Any]) -> None:
        _atomic_write_json(self.registry_path, payload)

    @staticmethod
    def _allowed_report(path: Path, roots: list[Path]) -> bool:
        if path.suffix.lower() not in {".html", ".htm"}:
            return False
        for root in roots:
            try:
                relative = path.relative_to(root)
            except ValueError:
                continue
            if relative.parts and relative.parts[0] == ".codex-artifacts":
                return True
        return False

    def register_report(self, request: dict[str, Any]) -> dict[str, Any]:
        report_id = request.get("reportId")
        raw_path = request.get("path")
        raw_roots = request.get("repositoryRoots")
        if not isinstance(report_id, str) or not report_id:
            raise ValueError("reportId 缺失")
        if not isinstance(raw_path, str) or not isinstance(raw_roots, list):
            raise ValueError("报告路径或仓库范围缺失")
        path = Path(raw_path).expanduser().resolve()
        roots = [
            Path(value).expanduser().resolve()
            for value in raw_roots
            if isinstance(value, str)
        ]
        if not roots or not self._allowed_report(path, roots):
            raise ValueError("报告必须位于已注册仓库的 .codex-artifacts 目录")
        agent = request.get("agent")
        subject = request.get("subject")
        if subject is not None and (
            not isinstance(subject, str) or not subject.strip()
        ):
            raise ValueError("报告名称无效")
        if agent is not None:
            if not isinstance(agent, dict):
                raise ValueError("Agent 信息无效")
            if agent.get("client") not in {"codex", "claude"}:
                raise ValueError("Agent client 无效")
            if not isinstance(agent.get("sessionId"), str) or not agent["sessionId"]:
                raise ValueError("Agent sessionId 缺失")
            cwd = Path(str(agent.get("cwd") or "")).expanduser().resolve()
            if not any(cwd == root or root in cwd.parents for root in roots):
                raise ValueError("Agent 工作目录不在已注册仓库中")
            agent = {**agent, "cwd": str(cwd)}
        with self.lock:
            registry = self._load()
            existing = registry["reports"].get(report_id) or {}
            report_token = existing.get("reportToken") or secrets.token_urlsafe(32)
            registry["reports"][report_id] = {
                "path": str(path),
                "repositoryRoots": [str(root) for root in roots],
                "reportToken": report_token,
                "agent": agent,
                "subject": subject.strip() if isinstance(subject, str) else path.stem,
                "completion": None,
                "updatedAt": time.time(),
            }
            self._save(registry)
        return {
            "reportToken": report_token,
            "agentBound": agent is not None,
        }

    def _entry(
        self,
        registry: dict[str, Any],
        report_id: str,
        token: str,
    ) -> dict[str, Any]:
        entry = registry["reports"].get(report_id)
        if not isinstance(entry, dict):
            raise ValueError("报告未注册")
        if not hmac.compare_digest(str(entry.get("reportToken") or ""), token):
            raise PermissionError("报告 token 无效")
        path = Path(entry["path"]).resolve()
        roots = [Path(value).resolve() for value in entry["repositoryRoots"]]
        if not self._allowed_report(path, roots):
            raise ValueError("报告路径已超出注册范围")
        return entry

    def write_comments(
        self,
        report_id: str,
        token: str,
        expected_revision: int,
        comments: list[Any],
    ) -> dict[str, Any]:
        if not isinstance(comments, list):
            raise ValueError("comments 必须为数组")
        with self.lock:
            registry = self._load()
            entry = self._entry(registry, report_id, token)
            path = Path(entry["path"]).resolve()
            source = path.read_text()
            current = extract_comments(source)
            if current["reportId"] != report_id:
                raise ValueError("报告内嵌 reportId 不匹配")
            if int(current.get("revision") or 0) != int(expected_revision):
                raise ConflictError("当前 HTML 已由其他页面更新，请重新打开后继续评论")
            payload = {
                "schemaVersion": 2,
                "reportId": report_id,
                "revision": int(expected_revision) + 1,
                "updatedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "comments": comments,
            }
            updated = replace_comments_block(source, payload)
            payload = extract_comments(updated)
            mode = stat.S_IMODE(path.stat().st_mode)
            _atomic_write(path, updated.encode(), mode=mode)
            return payload

    def read_comments(
        self,
        report_id: str,
        token: str,
    ) -> dict[str, Any]:
        with self.lock:
            registry = self._load()
            entry = self._entry(registry, report_id, token)
            path = Path(entry["path"]).resolve()
            payload = extract_comments(path.read_text())
            if payload["reportId"] != report_id:
                raise ValueError("报告内嵌 reportId 不匹配")
            return payload

    def complete_review(
        self,
        report_id: str,
        token: str,
        revision: int,
        comment_ids: list[Any],
        batch_id: str,
    ) -> dict[str, Any]:
        if not isinstance(comment_ids, list) or not comment_ids:
            raise ValueError("本次发送必须包含待处理评论")
        normalized_ids = [
            value for value in comment_ids
            if isinstance(value, str) and value
        ]
        if len(normalized_ids) != len(comment_ids) or len(set(normalized_ids)) != len(
            normalized_ids
        ):
            raise ValueError("本次发送的评论 ID 无效")
        if not isinstance(batch_id, str) or not batch_id.strip():
            raise ValueError("本次发送的批次 ID 无效")
        with self.lock:
            registry = self._load()
            entry = self._entry(registry, report_id, token)
            path = Path(entry["path"]).resolve()
            source = path.read_text()
            embedded = extract_comments(source)
            if int(embedded.get("revision") or 0) != int(revision):
                raise ConflictError("评论尚未全部写入当前 HTML")
            by_id = {
                str(comment.get("id") or ""): comment
                for comment in embedded["comments"]
            }
            selected = [by_id.get(comment_id) for comment_id in normalized_ids]
            if any(comment is None for comment in selected):
                raise ValueError("本次发送包含不存在的评论")
            if any(comment.get("status") != "pending" for comment in selected):
                raise ValueError("本次发送只允许包含未处理评论")
            agent = entry.get("agent")
            if not isinstance(agent, dict):
                raise ValueError("该报告未绑定生成它的 Agent")
            launch_agent = {
                **agent,
                "reportSubject": str(entry.get("subject") or path.stem),
                "reviewBatchId": batch_id,
                "reviewCommentIds": normalized_ids,
            }
            sent_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            selected_ids = set(normalized_ids)
            for comment in embedded["comments"]:
                if comment.get("id") in selected_ids:
                    comment["status"] = "processing"
                    comment["aiBatchId"] = batch_id
                    comment["aiSentAt"] = sent_at
                    comment.pop("resolvedAt", None)
            embedded["revision"] = int(revision) + 1
            embedded["updatedAt"] = sent_at
            updated = replace_comments_block(source, embedded)
            mode = stat.S_IMODE(path.stat().st_mode)
            _atomic_write(path, updated.encode(), mode=mode)
            try:
                self.launcher(launch_agent, path)
            except Exception:
                _atomic_write(path, source.encode(), mode=mode)
                raise
            completion = {
                "revision": embedded["revision"],
                "client": agent.get("client"),
                "agentStarted": True,
                "clientOpened": False,
                "status": "agent_started",
                "duplicate": False,
                "aiBatchId": batch_id,
                "commentIds": normalized_ids,
                "comments": embedded,
                "updatedAt": time.time(),
            }
            if agent.get("client") == "codex":
                try:
                    completion["clientOpened"] = bool(self.client_opener(agent))
                    if not completion["clientOpened"]:
                        completion["clientOpenError"] = "任务已恢复，但未能打开原窗口"
                except (OSError, RuntimeError, ValueError) as error:
                    completion["clientOpenError"] = str(error)
                if completion["clientOpened"]:
                    completion["status"] = "opened"
            entry["completion"] = completion
            self._save(registry)
            return completion


class HelperRequestHandler(BaseHTTPRequestHandler):
    server_version = "EasyCRHelper/1.0"

    def _origin(self) -> str | None:
        return self.headers.get("Origin")

    def _allowed_origin(self) -> bool:
        origin = self._origin()
        return origin in {
            None,
            "null",
            "http://127.0.0.1",
            f"http://127.0.0.1:{HELPER_PORT}",
            "http://localhost",
            f"http://localhost:{HELPER_PORT}",
        }

    def _send(self, status: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode()
        self.send_response(status)
        origin = self._origin()
        if origin in {"null", f"http://127.0.0.1:{HELPER_PORT}", f"http://localhost:{HELPER_PORT}"}:
            self.send_header("Access-Control-Allow-Origin", origin)
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Easy-CR-Token")
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self) -> None:
        if not self._allowed_origin():
            self._send(403, {"error": "Origin 不允许"})
            return
        self._send(204, {})

    def do_POST(self) -> None:
        if not self._allowed_origin():
            self._send(403, {"error": "Origin 不允许"})
            return
        try:
            length = int(self.headers.get("Content-Length") or 0)
            if length <= 0 or length > MAX_REQUEST_BYTES:
                raise ValueError("请求大小无效")
            payload = json.loads(self.rfile.read(length))
            if not isinstance(payload, dict):
                raise ValueError("请求必须为 JSON 对象")
            token = self.headers.get("X-Easy-CR-Token") or ""
            store: HelperStore = self.server.store  # type: ignore[attr-defined]
            master_token: str = self.server.master_token  # type: ignore[attr-defined]
            if self.path == "/api/health":
                if not hmac.compare_digest(master_token, token):
                    raise PermissionError("token 无效")
                result = {"ready": True, "port": HELPER_PORT}
            elif self.path == "/api/reports/register":
                if not hmac.compare_digest(master_token, token):
                    raise PermissionError("token 无效")
                result = store.register_report(payload)
            elif self.path == "/api/comments/write":
                result = store.write_comments(
                    str(payload.get("reportId") or ""),
                    token,
                    int(payload.get("expectedRevision") or 0),
                    payload.get("comments"),
                )
            elif self.path == "/api/comments/read":
                result = store.read_comments(
                    str(payload.get("reportId") or ""),
                    token,
                )
            elif self.path == "/api/reviews/complete":
                result = store.complete_review(
                    str(payload.get("reportId") or ""),
                    token,
                    int(payload.get("revision") or 0),
                    payload.get("commentIds"),
                    str(payload.get("aiBatchId") or ""),
                )
            else:
                self._send(404, {"error": "接口不存在"})
                return
            self._send(200, result)
        except ConflictError as error:
            self._send(409, {"error": str(error)})
        except PermissionError as error:
            self._send(403, {"error": str(error)})
        except (OSError, ValueError, json.JSONDecodeError) as error:
            self._send(400, {"error": str(error)})
        except RuntimeError as error:
            self._send(500, {"error": str(error)})

    def log_message(self, format: str, *args: Any) -> None:
        sys.stderr.write(
            "%s - - [%s] %s\n"
            % (self.address_string(), self.log_date_time_string(), format % args)
        )


def serve(
    host: str = HELPER_HOST,
    port: int = HELPER_PORT,
    token_path: Path = MASTER_TOKEN_PATH,
    config_dir: Path = CONFIG_DIR,
) -> None:
    if host != HELPER_HOST:
        raise ValueError("Easy CR helper 只能监听 127.0.0.1")
    master_token = ensure_master_token(token_path)
    server = ThreadingHTTPServer((host, port), HelperRequestHandler)
    server.store = HelperStore(config_dir)  # type: ignore[attr-defined]
    server.master_token = master_token  # type: ignore[attr-defined]
    server.serve_forever()


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    serve_parser = subparsers.add_parser("serve")
    serve_parser.add_argument("--host", default=HELPER_HOST)
    serve_parser.add_argument("--port", type=int, default=HELPER_PORT)
    serve_parser.add_argument("--token-file", type=Path, default=MASTER_TOKEN_PATH)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        serve(args.host, args.port, args.token_file)
        return 0
    except (OSError, RuntimeError, ValueError) as error:
        print(f"easy-cr helper: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
