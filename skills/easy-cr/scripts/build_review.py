#!/usr/bin/env python3
"""Render a business-sequenced, self-contained Easy CR HTML review."""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import shlex
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from easy_cr_config import CONFIG_PATH, TOKEN_PATH, resolve_semantic


SKILL_DIR = Path(__file__).resolve().parent.parent
TEMPLATE_PATH = SKILL_DIR / "assets" / "review-template.html"
GO_KEYWORDS = frozenset({
    "break", "default", "func", "interface", "select", "case", "defer", "go",
    "map", "struct", "chan", "else", "goto", "package", "switch", "const",
    "fallthrough", "if", "range", "type", "continue", "for", "import", "return",
    "var",
})
HUNK_PATTERN = re.compile(
    r"^@@ -(?P<old>\d+)(?:,(?P<old_count>\d+))? "
    r"\+(?P<new>\d+)(?:,(?P<new_count>\d+))? @@"
)
IDENTIFIER_PATTERN = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


@dataclass
class DiffLine:
    text: str
    kind: str
    old_line: int | None = None
    new_line: int | None = None


@dataclass
class DiffFile:
    path: str
    lines: list[DiffLine] = field(default_factory=list)
    added: int = 0
    deleted: int = 0

    @property
    def category(self) -> str:
        lowered = self.path.lower()
        if (
            lowered.endswith("_test.go")
            or "/test/" in lowered
            or "/tests/" in lowered
            or lowered.startswith("test/")
            or lowered.startswith("tests/")
        ):
            return "test"
        return "prod"


def run_git(repo: Path, *arguments: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        ["git", "-C", str(repo), "-c", "core.quotePath=false", *arguments],
        text=True,
        capture_output=True,
        check=False,
    )
    if check and result.returncode:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip() or "git command failed")
    return result


def parse_diff_path(header: str) -> str:
    parts = shlex.split(header)
    if len(parts) < 4 or parts[0:2] != ["diff", "--git"]:
        raise ValueError(f"invalid diff header: {header}")
    path = parts[3]
    return path[2:] if path.startswith("b/") else path


def parse_diff(raw_diff: str) -> list[DiffFile]:
    files: list[DiffFile] = []
    current: DiffFile | None = None
    old_line: int | None = None
    new_line: int | None = None

    for raw_line in raw_diff.splitlines():
        if raw_line.startswith("diff --git "):
            current = DiffFile(parse_diff_path(raw_line))
            current.lines.append(DiffLine(raw_line, "meta"))
            files.append(current)
            old_line = None
            new_line = None
            continue
        if current is None:
            continue
        if raw_line.startswith("+++ "):
            target = raw_line[4:]
            if target != "/dev/null":
                target = target[2:] if target.startswith("b/") else target
                current.path = target
            current.lines.append(DiffLine(raw_line, "meta"))
            continue
        hunk = HUNK_PATTERN.match(raw_line)
        if hunk:
            old_line = int(hunk.group("old"))
            new_line = int(hunk.group("new"))
            current.lines.append(DiffLine(raw_line, "hunk"))
            continue
        if old_line is None or new_line is None:
            current.lines.append(DiffLine(raw_line, "meta"))
            continue
        if raw_line.startswith("+") and not raw_line.startswith("+++"):
            current.lines.append(DiffLine(raw_line, "add", new_line=new_line))
            current.added += 1
            new_line += 1
        elif raw_line.startswith("-") and not raw_line.startswith("---"):
            current.lines.append(DiffLine(raw_line, "del", old_line=old_line))
            current.deleted += 1
            old_line += 1
        elif raw_line.startswith(" "):
            current.lines.append(
                DiffLine(raw_line, "ctx", old_line=old_line, new_line=new_line)
            )
            old_line += 1
            new_line += 1
        else:
            current.lines.append(DiffLine(raw_line, "meta"))
    return files


def inline_markup(value: str) -> str:
    escaped = html.escape(value)
    return re.sub(r"`([^`\n]+)`", r"<code>\1</code>", escaped)


def highlight_go_line(text: str, block_comment: bool) -> tuple[str, bool]:
    prefix = text[:1] if text[:1] in {"+", " ", "-"} else ""
    source = text[1:] if prefix else text
    output = [html.escape(prefix)]
    cursor = 0
    length = len(source)

    while cursor < length:
        if block_comment:
            end = source.find("*/", cursor)
            if end < 0:
                output.append(html.escape(source[cursor:]))
                return "".join(output), True
            output.append(html.escape(source[cursor:end + 2]))
            cursor = end + 2
            block_comment = False
            continue
        if source.startswith("//", cursor):
            output.append(html.escape(source[cursor:]))
            break
        if source.startswith("/*", cursor):
            end = source.find("*/", cursor + 2)
            if end < 0:
                output.append(html.escape(source[cursor:]))
                return "".join(output), True
            output.append(html.escape(source[cursor:end + 2]))
            cursor = end + 2
            continue
        char = source[cursor]
        if char in {'"', "'", "`"}:
            quote = char
            end = cursor + 1
            while end < length:
                if quote != "`" and source[end] == "\\":
                    end += 2
                    continue
                if source[end] == quote:
                    end += 1
                    break
                end += 1
            output.append(html.escape(source[cursor:end]))
            cursor = end
            continue
        identifier = IDENTIFIER_PATTERN.match(source, cursor)
        if identifier:
            symbol = identifier.group(0)
            if symbol in GO_KEYWORDS:
                output.append(symbol)
            else:
                byte_column = len(source[:cursor].encode("utf-8")) + 1
                output.append(
                    '<span class="code-identifier" '
                    f'data-symbol="{html.escape(symbol, quote=True)}" '
                    f'data-column="{byte_column}">{html.escape(symbol)}</span>'
                )
            cursor = identifier.end()
            continue
        output.append(html.escape(char))
        cursor += 1
    return "".join(output), block_comment


def render_file_card(item: DiffFile, index: int) -> str:
    rendered_lines: list[str] = []
    block_comment = False
    is_go = item.path.endswith(".go")
    for line in item.lines:
        if line.kind == "hunk":
            block_comment = False
        if is_go and line.kind in {"add", "ctx"}:
            body, block_comment = highlight_go_line(line.text, block_comment)
        else:
            body = html.escape(line.text)
        old_value = "" if line.old_line is None else str(line.old_line)
        new_value = "" if line.new_line is None else str(line.new_line)
        rendered_lines.append(
            f'<div class="line {line.kind}" data-old-line="{old_value}" '
            f'data-new-line="{new_value}"><span>{body}</span></div>'
        )
    label = item.category.upper()
    path = html.escape(item.path)
    return (
        f'<details id="file-{index}" class="file-card {item.category}" open '
        f'data-path="{html.escape(item.path, quote=True)}">\n'
        "  <summary>\n"
        f'    <span class="kind">{label}</span>\n'
        f"    <code>{path}</code>\n"
        f'    <span class="delta"><b>+{item.added}</b><i>-{item.deleted}</i></span>\n'
        "  </summary>\n"
        f'  <div class="diff">{"".join(rendered_lines)}</div>\n'
        "</details>"
    )


def render_nav(item: DiffFile, index: int) -> str:
    return (
        f'<button class="file-link {item.category}" data-target="file-{index}" '
        f'data-path="{html.escape(item.path, quote=True)}">'
        f'<span class="file-name">{html.escape(item.path)}</span>'
        f'<span class="delta"><b>+{item.added}</b><i>-{item.deleted}</i></span>'
        "</button>"
    )


def normalize_manifest(manifest: dict[str, Any], changed_paths: list[str]) -> dict[str, Any]:
    required_strings = ("scope", "summary", "boundary")
    for field_name in required_strings:
        if not isinstance(manifest.get(field_name), str) or not manifest[field_name].strip():
            raise ValueError(f"manifest.{field_name} must be a non-empty string")
    flow = manifest.get("flow", [])
    groups = manifest.get("groups", [])
    if not isinstance(flow, list) or not 3 <= len(flow) <= 6:
        raise ValueError("manifest.flow must contain 3-6 business timeline nodes")
    if not isinstance(groups, list) or not groups:
        raise ValueError("manifest.groups must be a non-empty list")

    seen: set[str] = set()
    known = set(changed_paths)
    normalized_groups: list[dict[str, Any]] = []
    for index, group in enumerate(groups):
        if not isinstance(group, dict):
            raise ValueError(f"manifest.groups[{index}] must be an object")
        files = group.get("files")
        if not isinstance(files, list):
            raise ValueError(f"manifest.groups[{index}].files must be a list")
        for path in files:
            if path not in known:
                raise ValueError(f"manifest group references unchanged file: {path}")
            if path in seen:
                raise ValueError(f"changed file belongs to multiple business stages: {path}")
            seen.add(path)
        normalized_groups.append(group)
    unlisted = [path for path in changed_paths if path not in seen]
    if unlisted:
        normalized_groups.append({
            "id": "other-changes",
            "title": "补充其他改动",
            "summary": "展示未归入主业务时序的辅助改动。",
            "points": ["确认与主链路的关系"],
            "files": unlisted,
        })
    result = dict(manifest)
    result["groups"] = normalized_groups
    return result


def render_logic_definitions(groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rendered = []
    for group in groups:
        rendered.append({
            "id": html.escape(str(group["id"]), quote=True),
            "title": inline_markup(str(group["title"])),
            "summary": inline_markup(str(group["summary"])),
            "points": [inline_markup(str(point)) for point in group.get("points", [])],
            "files": list(group["files"]),
        })
    return rendered


def replace_template(template: str, values: dict[str, str]) -> str:
    output = template
    for key, value in values.items():
        output = output.replace(f"@@{key}@@", value)
    unresolved = sorted(set(re.findall(r"@@[A-Z0-9_]+@@", output)))
    if unresolved:
        raise RuntimeError(f"unresolved template placeholders: {', '.join(unresolved)}")
    return output


def resolve_diff(repo: Path, base: str, head: str, context: int) -> tuple[str, dict[str, str]]:
    head_commit = run_git(repo, "rev-parse", "HEAD").stdout.strip()
    if head == "WORKTREE":
        raw_diff = run_git(
            repo,
            "diff",
            "--no-ext-diff",
            "--find-renames",
            f"--unified={context}",
            base,
            "--",
        ).stdout
        fingerprint = hashlib.sha256(
            f"{head_commit}\n{raw_diff}".encode("utf-8")
        ).hexdigest()
        return raw_diff, {
            "headCommit": head_commit,
            "reviewType": "worktree",
            "fingerprint": fingerprint,
        }
    resolved_head = run_git(repo, "rev-parse", head).stdout.strip()
    raw_diff = run_git(
        repo,
        "diff",
        "--no-ext-diff",
        "--find-renames",
        f"--unified={context}",
        base,
        head,
        "--",
    ).stdout
    return raw_diff, {
        "headCommit": resolved_head,
        "reviewType": "revision",
        "fingerprint": resolved_head,
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--base", required=True)
    parser.add_argument("--head", required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--context", type=int, default=10)
    parser.add_argument("--config-file", type=Path, default=CONFIG_PATH)
    parser.add_argument("--token-file", type=Path, default=TOKEN_PATH)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    repo = args.repo.expanduser().resolve()
    if not (repo / ".git").exists():
        raise RuntimeError(f"not a Git repository: {repo}")
    if args.context < 0 or args.context > 100:
        raise ValueError("context must be between 0 and 100")
    manifest = json.loads(args.manifest.expanduser().read_text())
    if not isinstance(manifest, dict):
        raise ValueError("manifest root must be an object")
    raw_diff, revision = resolve_diff(repo, args.base, args.head, args.context)
    files = parse_diff(raw_diff)
    if not files:
        raise RuntimeError("review range has no changed files")
    manifest = normalize_manifest(manifest, [item.path for item in files])
    semantic, warning = resolve_semantic(args.config_file, args.token_file)
    if warning:
        print(f"easy-cr: {warning}; 已生成基础模式 HTML", file=sys.stderr)

    head_commit = revision["headCommit"]
    metadata = run_git(
        repo,
        "show",
        "-s",
        "--format=%s%x00%an <%ae>%x00%ad",
        "--date=iso-strict",
        head_commit,
    ).stdout.rstrip("\n").split("\x00")
    git_subject, author, authored_at = (metadata + ["", "", ""])[:3]
    subject = str(manifest.get("subject") or git_subject or "Code Review")
    added = sum(item.added for item in files)
    deleted = sum(item.deleted for item in files)
    report = {
        "commit": revision["fingerprint"],
        "subject": subject,
        "files": len(files),
        "added": added,
        "deleted": deleted,
        "repo": str(repo),
        "base": args.base,
        "head": args.head,
        "headCommit": head_commit,
        "reviewType": revision["reviewType"],
        "fingerprint": revision["fingerprint"],
        "context": args.context,
        "semantic": semantic,
    }
    flow_html = "".join(
        f'<div class="flow-node"><b>{inline_markup(str(node["title"]))}</b>'
        f'{inline_markup(str(node["detail"]))}</div>'
        for node in manifest["flow"]
    )
    checklist = "".join(
        f'<label><input type="checkbox"> {inline_markup(str(point))}</label>'
        for point in manifest.get("review_points", [])
    )
    short_commit = head_commit[:8]
    values = {
        "TITLE": html.escape(f"CR · {subject} · {short_commit}"),
        "SUBJECT": inline_markup(subject),
        "SUBTITLE": (
            f"<code>{html.escape(short_commit)}</code> · {html.escape(author)} · "
            f"{html.escape(authored_at)}"
        ),
        "SCOPE": inline_markup(manifest["scope"]),
        "FILE_COUNT": str(len(files)),
        "ADDED": str(added),
        "DELETED": str(deleted),
        "FILE_NAV": "".join(render_nav(item, index) for index, item in enumerate(files)),
        "OVERVIEW_TITLE": inline_markup(str(manifest.get("overview_title", "改动概括"))),
        "SUMMARY": inline_markup(manifest["summary"]),
        "BOUNDARY": inline_markup(manifest["boundary"]),
        "BUSINESS_FLOW": flow_html,
        "CHECKLIST": checklist,
        "DIFFS": "".join(render_file_card(item, index) for index, item in enumerate(files)),
        "REPORT_JSON": json.dumps(report, ensure_ascii=False),
        "LOGIC_JSON": json.dumps(
            render_logic_definitions(manifest["groups"]),
            ensure_ascii=False,
        ),
    }
    rendered = replace_template(TEMPLATE_PATH.read_text(), values)
    args.output.expanduser().parent.mkdir(parents=True, exist_ok=True)
    args.output.expanduser().write_text(rendered)
    print(args.output.expanduser().resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
