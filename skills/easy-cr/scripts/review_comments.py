#!/usr/bin/env python3
"""Read and replace Easy CR's embedded human review comments."""

from __future__ import annotations

import json
import re
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any


COMMENTS_START = "<!-- EASY-CR-COMMENTS:START -->"
COMMENTS_END = "<!-- EASY-CR-COMMENTS:END -->"
COMMENTS_ELEMENT_ID = "easy-cr-comments-data"
COMMENT_STATUSES = frozenset({"pending", "processing", "resolved"})
COMMENT_STATUS_LABELS = {
    "pending": "未处理",
    "processing": "处理中",
    "resolved": "已解决",
}
_DATA_PATTERN = re.compile(
    rf'<script\s+id="{COMMENTS_ELEMENT_ID}"\s+type="application/json">'
    r"(?P<payload>.*?)</script>",
    re.DOTALL,
)
_BLOCK_PATTERN = re.compile(
    rf"{re.escape(COMMENTS_START)}\s*"
    rf'<script\s+id="{COMMENTS_ELEMENT_ID}"\s+type="application/json">'
    r".*?</script>\s*"
    rf"{re.escape(COMMENTS_END)}",
    re.DOTALL,
)


def _normalize_comment(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("Easy CR comment must be an object")
    comment = deepcopy(value)
    status = comment.get("status")
    if status is None:
        status = "resolved" if comment.get("resolved") is True else "pending"
    if status not in COMMENT_STATUSES:
        raise ValueError(f"Easy CR comment status is invalid: {status}")
    comment["status"] = status
    comment.pop("resolved", None)
    if not isinstance(comment.get("replies"), list):
        comment["replies"] = []
    return comment


def _validate_payload(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("Easy CR comments payload must be an object")
    if payload.get("schemaVersion") != 2:
        raise ValueError("Easy CR comments schemaVersion must be 2")
    report_id = payload.get("reportId")
    if not isinstance(report_id, str) or not report_id:
        raise ValueError("Easy CR comments reportId must be a non-empty string")
    comments = payload.get("comments")
    if not isinstance(comments, list):
        raise ValueError("Easy CR comments must be a list")
    normalized = deepcopy(payload)
    normalized["revision"] = int(normalized.get("revision") or 0)
    normalized["comments"] = [_normalize_comment(comment) for comment in comments]
    return normalized


def _safe_json(payload: dict[str, Any]) -> str:
    serialized = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    return (
        serialized
        .replace("&", "\\u0026")
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
    )


def comments_block(payload: dict[str, Any]) -> str:
    payload = _validate_payload(payload)
    return (
        f"{COMMENTS_START}\n"
        f'<script id="{COMMENTS_ELEMENT_ID}" type="application/json">'
        f"{_safe_json(payload)}</script>\n"
        f"{COMMENTS_END}"
    )


def empty_comments_block(report_id: str) -> str:
    return comments_block({
        "schemaVersion": 2,
        "reportId": report_id,
        "revision": 0,
        "updatedAt": None,
        "comments": [],
    })


def extract_comments(html_text: str) -> dict[str, Any]:
    blocks = _BLOCK_PATTERN.findall(html_text)
    if len(blocks) != 1:
        raise ValueError("Easy CR report must contain exactly one comments block")
    match = _DATA_PATTERN.search(blocks[0])
    if match is None:
        raise ValueError("Easy CR comments data element is missing")
    try:
        payload = json.loads(match.group("payload"))
    except json.JSONDecodeError as error:
        raise ValueError(f"Easy CR comments JSON is invalid: {error}") from error
    return _validate_payload(payload)


def replace_comments_block(
    html_text: str,
    payload: dict[str, Any],
) -> str:
    payload = _validate_payload(payload)
    current = extract_comments(html_text)
    if current["reportId"] != payload["reportId"]:
        raise ValueError("Easy CR comments reportId does not match this report")
    replacement = comments_block(payload)
    return _BLOCK_PATTERN.sub(lambda _: replacement, html_text, count=1)


def comments_markdown(payload: dict[str, Any], subject: str = "Easy CR") -> str:
    payload = _validate_payload(payload)
    lines = [f"# Code Review · {subject}", ""]
    comments = payload["comments"]
    if not comments:
        return "\n".join(lines + ["暂无评论。"])
    for index, comment in enumerate(comments, 1):
        scope = str(comment.get("scope") or "code")
        target = comment.get("target") if isinstance(comment.get("target"), dict) else {}
        location = "全文"
        if scope == "chapter":
            location = f"章节 {target.get('chapterId', '')}".strip()
        elif scope == "code":
            repo_id = target.get("repoId") or ""
            path = target.get("path") or ""
            line = target.get("lineLabel") or target.get("anchorId") or ""
            location = f"{repo_id}:{path}:{line}".strip(":")
        state = COMMENT_STATUS_LABELS[comment["status"]]
        body = str(comment.get("body") or comment.get("text") or "")
        lines.extend([
            f"{index}. `{location}` · {state}",
            f"   {body.replace(chr(10), chr(10) + '   ')}",
        ])
        for reply in comment.get("replies") or []:
            reply_body = str(reply.get("body") or reply.get("text") or "")
            lines.append(
                f"   - 回复：{reply_body.replace(chr(10), chr(10) + '     ')}"
            )
        lines.append("")
    return "\n".join(lines).rstrip()


def mark_batch_resolved(
    payload: dict[str, Any],
    batch_id: str,
    reply_body: str | None = None,
) -> dict[str, Any]:
    if not isinstance(batch_id, str) or not batch_id.strip():
        raise ValueError("Easy CR aiBatchId must be a non-empty string")
    updated = _validate_payload(payload)
    matched = False
    resolved_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    reply_text = (reply_body or "AI 已处理本条评论。").strip()
    for comment in updated["comments"]:
        if (
            comment.get("aiBatchId") == batch_id
            and comment["status"] == "processing"
        ):
            comment.setdefault("replies", []).append({
                "id": f"reply-ai-{batch_id}-{len(comment.get('replies') or []) + 1}",
                "body": reply_text,
                "author": "ai",
                "createdAt": resolved_at,
                "updatedAt": None,
            })
            comment["status"] = "resolved"
            comment["resolvedAt"] = resolved_at
            matched = True
    if not matched:
        raise ValueError(f"没有处于处理中的评论批次：{batch_id}")
    updated["revision"] = int(updated.get("revision") or 0) + 1
    updated["updatedAt"] = resolved_at
    return updated
