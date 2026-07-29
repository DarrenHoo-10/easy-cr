#!/usr/bin/env python3
"""Render a guided, multi-repository, self-contained Easy CR HTML review."""

from __future__ import annotations

import argparse
import difflib
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

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from easy_cr_config import CONFIG_PATH, resolve_semantic
from easy_cr_helper import prepare_report_helper
from review_comments import (
    comments_block,
    empty_comments_block,
    extract_comments,
)


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
DISPLAY_MODES = frozenset({"diff-only", "compact-context", "guided"})
DEPENDENCY_FILES = frozenset({
    "go.mod", "go.sum", "package-lock.json", "yarn.lock", "pnpm-lock.yaml",
    "bun.lock", "bun.lockb", "cargo.lock", "poetry.lock", "pipfile.lock",
    "requirements.txt", "composer.lock", "gemfile.lock",
})
REVIEW_STATE_START = "<!-- EASY-CR-REVIEW-STATE:START -->"
REVIEW_STATE_END = "<!-- EASY-CR-REVIEW-STATE:END -->"
REVIEW_STATE_ELEMENT_ID = "easy-cr-review-state"
REVIEW_STATE_PATTERN = re.compile(
    rf"{re.escape(REVIEW_STATE_START)}\s*"
    rf'<script\s+id="{REVIEW_STATE_ELEMENT_ID}"\s+type="application/json">'
    r"(?P<payload>.*?)</script>\s*"
    rf"{re.escape(REVIEW_STATE_END)}",
    re.DOTALL,
)


@dataclass
class DiffLine:
    text: str
    kind: str
    old_line: int | None = None
    new_line: int | None = None
    iteration_change: bool = False


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
            lowered.endswith(("_test.go", ".test.js", ".test.ts", ".spec.js", ".spec.ts"))
            or "/test/" in lowered
            or "/tests/" in lowered
            or lowered.startswith(("test/", "tests/"))
        ):
            return "test"
        return "prod"


@dataclass
class RepositoryReview:
    id: str
    label: str
    root: Path
    base: str
    head: str
    context: int
    revision: dict[str, str]
    files: list[DiffFile]
    subject: str
    author: str
    authored_at: str

    @property
    def files_by_path(self) -> dict[str, DiffFile]:
        return {item.path: item for item in self.files}

    def payload(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "label": self.label,
            "root": str(self.root),
            "base": self.base,
            "head": self.head,
            "headCommit": self.revision["headCommit"],
            "reviewType": self.revision["reviewType"],
            "fingerprint": self.revision["fingerprint"],
            "context": self.context,
            "files": len(self.files),
            "added": sum(item.added for item in self.files),
            "deleted": sum(item.deleted for item in self.files),
        }


def run_git(
    repo: Path,
    *arguments: str,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        ["git", "-C", str(repo), "-c", "core.quotePath=false", *arguments],
        text=True,
        capture_output=True,
        check=False,
    )
    if check and result.returncode:
        raise RuntimeError(
            result.stderr.strip() or result.stdout.strip() or "git command failed"
        )
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


def json_for_script(value: Any) -> str:
    return (
        json.dumps(value, ensure_ascii=False)
        .replace("&", "\\u0026")
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("\u2028", "\\u2028")
        .replace("\u2029", "\\u2029")
    )


def review_state_block(payload: dict[str, Any]) -> str:
    return (
        f"{REVIEW_STATE_START}\n"
        f'<script id="{REVIEW_STATE_ELEMENT_ID}" type="application/json">'
        f"{json_for_script(payload)}</script>\n"
        f"{REVIEW_STATE_END}"
    )


def extract_review_state(html_text: str) -> dict[str, Any] | None:
    match = REVIEW_STATE_PATTERN.search(html_text)
    if match is None:
        return None
    try:
        payload = json.loads(match.group("payload"))
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def build_review_state(
    report_id: str,
    repositories: list[RepositoryReview],
    previous_state: dict[str, Any] | None,
) -> dict[str, Any]:
    files: dict[str, Any] = {}
    for repository in repositories:
        for item in repository.files:
            files[f"{repository.id}:{item.path}"] = {
                "added": [
                    hashlib.sha256(line.text.encode("utf-8")).hexdigest()
                    for line in item.lines
                    if line.kind == "add"
                ],
            }
    return {
        "schemaVersion": 1,
        "reportId": report_id,
        "previousReportId": (
            previous_state.get("reportId")
            if isinstance(previous_state, dict)
            else None
        ),
        "iteration": (
            int(previous_state.get("iteration") or 1) + 1
            if isinstance(previous_state, dict)
            else 1
        ),
        "files": files,
    }


def mark_iteration_changes(
    repositories: list[RepositoryReview],
    previous_state: dict[str, Any] | None,
) -> None:
    if not previous_state:
        return
    previous_files = previous_state.get("files")
    if not isinstance(previous_files, dict):
        return
    for repository in repositories:
        for item in repository.files:
            previous_file = previous_files.get(f"{repository.id}:{item.path}")
            previous_added = (
                previous_file.get("added")
                if isinstance(previous_file, dict)
                else None
            )
            if not isinstance(previous_added, list):
                for line in item.lines:
                    if line.kind == "add":
                        line.iteration_change = True
                continue
            current_lines = [line for line in item.lines if line.kind == "add"]
            current_added = [
                hashlib.sha256(line.text.encode("utf-8")).hexdigest()
                for line in current_lines
            ]
            unchanged_indexes: set[int] = set()
            matcher = difflib.SequenceMatcher(
                None,
                previous_added,
                current_added,
                autojunk=False,
            )
            for block in matcher.get_matching_blocks():
                unchanged_indexes.update(
                    range(block.b, block.b + block.size)
                )
            for index, line in enumerate(current_lines):
                line.iteration_change = index not in unchanged_indexes


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


def line_anchor(repo_id: str, path: str, line: DiffLine) -> str:
    side = "new" if line.new_line is not None else (
        "old" if line.old_line is not None else line.kind
    )
    number = line.new_line if line.new_line is not None else line.old_line
    digest = hashlib.sha1(line.text.encode("utf-8")).hexdigest()[:10]
    return f"{repo_id}:{path}:{side}:{number or 0}:{digest}"


def render_file_card(
    item: DiffFile,
    index: int,
    repo_id: str,
    repo_label: str,
) -> str:
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
        anchor = line_anchor(repo_id, item.path, line)
        classes = f"line {line.kind}"
        if line.iteration_change:
            classes += " iteration-change"
        rendered_lines.append(
            f'<div class="{classes}" data-old-line="{old_value}" '
            f'data-new-line="{new_value}" '
            f'data-anchor="{html.escape(anchor, quote=True)}">'
            f"<span>{body}</span></div>"
        )
    path = html.escape(item.path)
    label = html.escape(repo_label)
    key = f"{repo_id}:{item.path}"
    return (
        f'<details id="file-{index}" class="file-card {item.category}" open '
        f'data-file-key="{html.escape(key, quote=True)}" '
        f'data-repo-id="{html.escape(repo_id, quote=True)}" '
        f'data-path="{html.escape(item.path, quote=True)}">\n'
        "  <summary>\n"
        f'    <span class="repo-label">{label}</span>\n'
        f"    <code>{path}</code>\n"
        f'    <span class="delta"><b>+{item.added}</b><i>-{item.deleted}</i></span>\n'
        "  </summary>\n"
        f'  <div class="diff">{"".join(rendered_lines)}</div>\n'
        "</details>"
    )


def resolve_diff(
    repo: Path,
    base: str,
    head: str,
    context: int,
) -> tuple[str, dict[str, str]]:
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


def commit_metadata(repo: Path, commit: str) -> tuple[str, str, str]:
    metadata = run_git(
        repo,
        "show",
        "-s",
        "--format=%s%x00%an <%ae>%x00%ad",
        "--date=iso-strict",
        commit,
    ).stdout.rstrip("\n").split("\x00")
    values = (metadata + ["", "", ""])[:3]
    return values[0], values[1], values[2]


def require_string(payload: dict[str, Any], field_name: str, context: str) -> str:
    value = payload.get(field_name)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{context}.{field_name} must be a non-empty string")
    return value.strip()


def valid_identifier(value: Any, context: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]*", value)
    ):
        raise ValueError(f"{context} must be a stable identifier")
    return value


def resolve_repository_specs(
    manifest: dict[str, Any],
    args: argparse.Namespace,
) -> tuple[int, list[dict[str, Any]]]:
    schema_version = manifest.get("schema_version", 1)
    if schema_version == 2:
        repositories = manifest.get("repositories")
        if not isinstance(repositories, list) or not repositories:
            raise ValueError("manifest.repositories must be a non-empty list")
        if args.repo is not None or args.base is not None or args.head is not None:
            raise ValueError(
                "schema v2 reads repository revisions from the manifest; "
                "do not pass --repo/--base/--head"
            )
        return 2, repositories
    if schema_version != 1:
        raise ValueError("manifest.schema_version must be 1 or 2")
    if args.repo is None or args.base is None or args.head is None:
        raise ValueError("legacy manifest requires --repo, --base and --head")
    return 1, [{
        "id": "default",
        "label": args.repo.expanduser().resolve().name,
        "root": str(args.repo),
        "base": args.base,
        "head": args.head,
        "context": args.context,
    }]


def load_repositories(
    specs: list[dict[str, Any]],
    default_context: int,
) -> list[RepositoryReview]:
    reviews: list[RepositoryReview] = []
    seen: set[str] = set()
    for index, spec in enumerate(specs):
        context_name = f"manifest.repositories[{index}]"
        if not isinstance(spec, dict):
            raise ValueError(f"{context_name} must be an object")
        repo_id = valid_identifier(spec.get("id"), f"{context_name}.id")
        if repo_id in seen:
            raise ValueError(f"duplicate repository id: {repo_id}")
        seen.add(repo_id)
        label = str(spec.get("label") or repo_id)
        root_value = spec.get("root")
        if not isinstance(root_value, str) or not root_value:
            raise ValueError(f"{context_name}.root must be a non-empty string")
        root = Path(root_value).expanduser().resolve()
        if not (root / ".git").exists():
            raise RuntimeError(f"not a Git repository: {root}")
        base = require_string(spec, "base", context_name)
        head = require_string(spec, "head", context_name)
        context = spec.get("context", default_context)
        if not isinstance(context, int) or context < 0 or context > 100:
            raise ValueError(f"{context_name}.context must be between 0 and 100")
        raw_diff, revision = resolve_diff(root, base, head, context)
        files = parse_diff(raw_diff)
        if not files:
            raise RuntimeError(f"review range has no changed files: {repo_id}")
        subject, author, authored_at = commit_metadata(
            root,
            revision["headCommit"],
        )
        reviews.append(RepositoryReview(
            id=repo_id,
            label=label,
            root=root,
            base=base,
            head=head,
            context=context,
            revision=revision,
            files=files,
            subject=subject,
            author=author,
            authored_at=authored_at,
        ))
    return reviews


def is_import_only(item: DiffFile) -> bool:
    changed = {
        index
        for index, line in enumerate(item.lines)
        if line.kind in {"add", "del"} and line.text[1:].strip()
    }
    return bool(changed) and changed <= import_change_indexes(item)


def import_change_indexes(item: DiffFile) -> set[int]:
    indexes: set[int] = set()
    in_block = False
    standalone = re.compile(
        r"^(?:import\b(?!\s*\()|from\b.*\bimport\b|using\b|"
        r".*\brequire\(.*\))"
    )
    for index, line in enumerate(item.lines):
        source = line.text[1:].strip() if line.text else ""
        if source.startswith("import ("):
            in_block = True
            if line.kind in {"add", "del"}:
                indexes.add(index)
            continue
        if in_block:
            if line.kind in {"add", "del"}:
                indexes.add(index)
            if source == ")":
                in_block = False
            continue
        if line.kind in {"add", "del"} and standalone.match(source):
            indexes.add(index)
    return indexes


def default_display_mode(item: DiffFile) -> str:
    lowered = item.path.lower()
    name = Path(lowered).name
    generated = (
        "/gen/" in lowered
        or "/generated/" in lowered
        or "/kitex_gen/" in lowered
        or name.endswith((".gen.go", ".pb.go", "_gen.go", ".generated.ts"))
    )
    if name in DEPENDENCY_FILES or generated or is_import_only(item):
        return "diff-only"
    return "compact-context"


def normalize_code_reference(
    raw: Any,
    repositories: dict[str, RepositoryReview],
    context: str,
) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ValueError(f"{context} must be an object")
    repo_id = valid_identifier(raw.get("repo_id"), f"{context}.repo_id")
    repository = repositories.get(repo_id)
    if repository is None:
        raise ValueError(f"{context} references unknown repository: {repo_id}")
    path = raw.get("path")
    if not isinstance(path, str) or path not in repository.files_by_path:
        raise ValueError(f"{context} references unchanged file: {repo_id}:{path}")
    item = repository.files_by_path[path]
    display_mode = raw.get("display_mode") or default_display_mode(item)
    if display_mode not in DISPLAY_MODES:
        raise ValueError(f"{context}.display_mode is invalid: {display_mode}")
    ranges = raw.get("ranges", [])
    if not isinstance(ranges, list):
        raise ValueError(f"{context}.ranges must be a list")
    normalized_ranges: list[dict[str, int]] = []
    changed_lines = {
        line.new_line if line.new_line is not None else line.old_line
        for line in item.lines
        if line.kind in {"add", "del"}
        and (line.new_line is not None or line.old_line is not None)
    }
    for range_index, value in enumerate(ranges):
        range_context = f"{context}.ranges[{range_index}]"
        if not isinstance(value, dict):
            raise ValueError(f"{range_context} must be an object")
        start = value.get("start")
        end = value.get("end")
        if (
            not isinstance(start, int)
            or not isinstance(end, int)
            or start <= 0
            or end < start
        ):
            raise ValueError(f"{range_context} must contain valid start/end")
        if not any(start <= line <= end for line in changed_lines):
            raise ValueError(f"{range_context} must include a changed line")
        normalized_ranges.append({"start": start, "end": end})
    return {
        "repoId": repo_id,
        "path": path,
        "fileKey": f"{repo_id}:{path}",
        "displayMode": display_mode,
        "ranges": normalized_ranges,
        "annotation": str(raw.get("annotation") or ""),
    }


def normalized_chapter(
    raw: Any,
    chapter_index: int,
    repositories: dict[str, RepositoryReview],
) -> dict[str, Any]:
    context = f"manifest.chapters[{chapter_index}]"
    if not isinstance(raw, dict):
        raise ValueError(f"{context} must be an object")
    chapter_id = valid_identifier(raw.get("id"), f"{context}.id")
    title = require_string(raw, "title", context)
    goal = str(raw.get("goal") or raw.get("summary") or title)
    summary = str(raw.get("summary") or goal)
    steps = raw.get("steps")
    if not isinstance(steps, list) or not steps:
        raise ValueError(f"{context}.steps must be a non-empty list")
    normalized_steps: list[dict[str, Any]] = []
    step_ids: set[str] = set()
    for step_index, step in enumerate(steps):
        step_context = f"{context}.steps[{step_index}]"
        if not isinstance(step, dict):
            raise ValueError(f"{step_context} must be an object")
        step_id = valid_identifier(step.get("id"), f"{step_context}.id")
        if step_id in step_ids:
            raise ValueError(f"duplicate step id in {chapter_id}: {step_id}")
        step_ids.add(step_id)
        code = step.get("code")
        if not isinstance(code, list) or not code:
            raise ValueError(f"{step_context}.code must be a non-empty list")
        normalized_code = [
            normalize_code_reference(
                reference,
                repositories,
                f"{step_context}.code[{code_index}]",
            )
            for code_index, reference in enumerate(code)
        ]
        normalized_code = [
            reference
            for reference in normalized_code
            if repositories[reference["repoId"]]
            .files_by_path[reference["path"]]
            .category != "test"
        ]
        normalized_steps.append({
            "id": step_id,
            "title": require_string(step, "title", step_context),
            "explanation": require_string(step, "explanation", step_context),
            "goal": str(step.get("goal") or ""),
            "decision": str(step.get("decision") or ""),
            "result": str(step.get("result") or ""),
            "code": normalized_code,
        })
    return {
        "id": chapter_id,
        "title": title,
        "goal": goal,
        "summary": summary,
        "points": [str(point) for point in raw.get("points", [])],
        "steps": normalized_steps,
    }


def legacy_chapters(
    manifest: dict[str, Any],
    repository: RepositoryReview,
) -> list[dict[str, Any]]:
    groups = manifest.get("groups")
    if not isinstance(groups, list) or not groups:
        raise ValueError("manifest.groups must be a non-empty list")
    chapters: list[dict[str, Any]] = []
    known = repository.files_by_path
    seen: set[str] = set()
    for index, group in enumerate(groups):
        context = f"manifest.groups[{index}]"
        if not isinstance(group, dict):
            raise ValueError(f"{context} must be an object")
        files = group.get("files")
        if not isinstance(files, list) or not files:
            raise ValueError(f"{context}.files must be a non-empty list")
        references = []
        for path in files:
            if path not in known:
                raise ValueError(f"manifest group references unchanged file: {path}")
            if path in seen:
                raise ValueError(f"changed file belongs to multiple business stages: {path}")
            seen.add(path)
            item = known[path]
            if item.category == "test":
                continue
            references.append({
                "repoId": "default",
                "path": path,
                "fileKey": f"default:{path}",
                "displayMode": default_display_mode(item),
                "ranges": [],
                "annotation": "",
            })
        chapter_id = valid_identifier(group.get("id"), f"{context}.id")
        title = require_string(group, "title", context)
        summary = require_string(group, "summary", context)
        chapters.append({
            "id": chapter_id,
            "title": title,
            "goal": summary,
            "summary": summary,
            "points": [str(point) for point in group.get("points", [])],
            "steps": [{
                "id": f"{chapter_id}-review",
                "title": title,
                "goal": "",
                "decision": "",
                "result": "",
                "explanation": summary,
                "code": references,
            }],
        })
    return chapters


def is_full_diff_only(item: DiffFile) -> bool:
    return (
        item.category == "test"
        or Path(item.path.lower()).name in DEPENDENCY_FILES
        or is_import_only(item)
    )


def validate_diff_coverage(
    chapters: list[dict[str, Any]],
    repositories: list[RepositoryReview],
) -> None:
    references_by_key: dict[str, list[dict[str, Any]]] = {}
    for reference in (
        reference
        for chapter in chapters
        for step in chapter["steps"]
        for reference in step["code"]
    ):
        references_by_key.setdefault(reference["fileKey"], []).append(reference)
    for repository in repositories:
        for item in repository.files:
            if is_full_diff_only(item):
                continue
            key = f"{repository.id}:{item.path}"
            references = references_by_key.get(key)
            if not references:
                raise ValueError(
                    f"{repository.id}:{item.path} 未归入业务章节"
                )
            if any(
                reference["displayMode"] != "guided"
                or not reference["ranges"]
                for reference in references
            ):
                continue
            ranges = [
                value
                for reference in references
                for value in reference["ranges"]
            ]
            import_indexes = import_change_indexes(item)
            for line_index, line in enumerate(item.lines):
                if line.kind not in {"add", "del"}:
                    continue
                if line_index in import_indexes:
                    continue
                number = (
                    line.new_line
                    if line.new_line is not None
                    else line.old_line
                )
                if number is None:
                    continue
                if not any(
                    value["start"] <= number <= value["end"]
                    for value in ranges
                ):
                    raise ValueError(
                        f"{repository.id}:{item.path}:{number} 未覆盖业务 Diff"
                    )


def normalize_manifest(
    manifest: dict[str, Any],
    schema_version: int,
    repositories: list[RepositoryReview],
) -> dict[str, Any]:
    for field_name in ("scope", "summary", "boundary"):
        require_string(manifest, field_name, "manifest")
    repository_map = {item.id: item for item in repositories}
    if schema_version == 1:
        flow = manifest.get("flow")
        if not isinstance(flow, list) or not 3 <= len(flow) <= 6:
            raise ValueError("manifest.flow must contain 3-6 business timeline nodes")
        chapters = legacy_chapters(manifest, repositories[0])
    else:
        raw_chapters = manifest.get("chapters")
        if not isinstance(raw_chapters, list) or not raw_chapters:
            raise ValueError("manifest.chapters must be a non-empty list")
        chapters = [
            normalized_chapter(chapter, index, repository_map)
            for index, chapter in enumerate(raw_chapters)
        ]
        ids = [chapter["id"] for chapter in chapters]
        if len(ids) != len(set(ids)):
            raise ValueError("manifest chapter ids must be unique")
        flow = manifest.get("flow")
        if flow is None:
            flow = [
                {"title": chapter["title"], "detail": chapter["goal"]}
                for chapter in chapters[:6]
            ]
        if not isinstance(flow, list) or not flow:
            raise ValueError("manifest.flow must be a non-empty list")
    validate_diff_coverage(chapters, repositories)
    normalized_flow = []
    for index, node in enumerate(flow):
        if not isinstance(node, dict):
            raise ValueError(f"manifest.flow[{index}] must be an object")
        normalized_flow.append({
            "title": require_string(node, "title", f"manifest.flow[{index}]"),
            "detail": require_string(node, "detail", f"manifest.flow[{index}]"),
        })
    return {
        "schemaVersion": 2,
        "subject": str(manifest.get("subject") or repositories[0].subject or "Code Review"),
        "scope": str(manifest["scope"]),
        "overviewTitle": str(manifest.get("overview_title") or "改动概括"),
        "summary": str(manifest["summary"]),
        "boundary": str(manifest["boundary"]),
        "flow": normalized_flow,
        "reviewPoints": [str(point) for point in manifest.get("review_points", [])],
        "chapters": chapters,
    }


def report_identifier(
    manifest: dict[str, Any],
    repositories: list[RepositoryReview],
) -> str:
    payload = {
        "manifest": manifest,
        "repositories": [
            {
                "id": repository.id,
                "fingerprint": repository.revision["fingerprint"],
            }
            for repository in repositories
        ],
    }
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _comment_candidate(
    repository: RepositoryReview,
    path: str,
    quote: str,
    old_line: int | None,
) -> DiffLine | None:
    item = repository.files_by_path.get(path)
    if item is None:
        return None
    quote_line = next(
        (line.strip() for line in quote.splitlines() if line.strip()),
        "",
    )
    candidates = [
        line
        for line in item.lines
        if line.kind in {"add", "ctx", "del"}
    ]
    if not candidates:
        return None
    def candidate_line(line: DiffLine) -> int:
        return line.new_line if line.new_line is not None else line.old_line or 0

    def score(line: DiffLine) -> float:
        source = line.text[1:].strip()
        similarity = (
            difflib.SequenceMatcher(
                None,
                quote_line,
                source,
                autojunk=False,
            ).ratio()
            if quote_line
            else 0.0
        )
        distance = (
            abs(candidate_line(line) - old_line)
            if old_line is not None
            else 0
        )
        return similarity - min(distance, 200) * 0.001

    return max(candidates, key=score)


def migrate_comments_block(
    previous_html: str | None,
    report_id: str,
    repositories: list[RepositoryReview],
) -> str:
    if not previous_html:
        return empty_comments_block(report_id)
    try:
        previous = extract_comments(previous_html)
    except ValueError:
        return empty_comments_block(report_id)
    repository_map = {repository.id: repository for repository in repositories}
    current_anchors = {
        line_anchor(repository.id, item.path, line)
        for repository in repositories
        for item in repository.files
        for line in item.lines
    }
    for comment in previous["comments"]:
        if comment.get("scope") != "code":
            continue
        target = comment.get("target")
        if not isinstance(target, dict):
            continue
        start_anchor = target.get("startAnchor")
        end_anchor = target.get("endAnchor")
        if start_anchor in current_anchors and end_anchor in current_anchors:
            target.pop("approximate", None)
            continue
        repository = repository_map.get(str(target.get("repoId") or ""))
        if repository is None:
            continue
        line_match = re.search(r"\d+", str(target.get("lineLabel") or ""))
        old_line = int(line_match.group()) if line_match else None
        candidate = _comment_candidate(
            repository,
            str(target.get("path") or ""),
            str(comment.get("quote") or ""),
            old_line,
        )
        if candidate is None:
            continue
        anchor = line_anchor(
            repository.id,
            str(target.get("path") or ""),
            candidate,
        )
        target["startAnchor"] = anchor
        target["endAnchor"] = anchor
        target["lineLabel"] = (
            f"+{candidate.new_line}"
            if candidate.new_line is not None
            else f"-{candidate.old_line or '?'}"
        )
        target["approximate"] = True
    previous["reportId"] = report_id
    previous["revision"] = int(previous.get("revision") or 0) + 1
    return comments_block(previous)


def replace_template(template: str, values: dict[str, str]) -> str:
    token_pattern = re.compile(r"@@(?P<name>[A-Z0-9_]+)@@")
    missing = sorted({
        match.group("name")
        for match in token_pattern.finditer(template)
        if match.group("name") not in values
    })
    if missing:
        raise RuntimeError(
            "unresolved template placeholders: "
            + ", ".join(f"@@{name}@@" for name in missing)
        )
    return token_pattern.sub(lambda match: values[match.group("name")], template)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path)
    parser.add_argument("--base")
    parser.add_argument("--head")
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--context", type=int, default=10)
    parser.add_argument("--config-file", type=Path, default=CONFIG_PATH)
    parser.add_argument("--token-file", type=Path)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.context < 0 or args.context > 100:
        raise ValueError("context must be between 0 and 100")
    manifest_path = args.manifest.expanduser()
    raw_manifest = json.loads(manifest_path.read_text())
    if not isinstance(raw_manifest, dict):
        raise ValueError("manifest root must be an object")
    output = args.output.expanduser().resolve()
    previous_html = output.read_text() if output.is_file() else None
    previous_state = (
        extract_review_state(previous_html)
        if previous_html is not None
        else None
    )
    schema_version, specs = resolve_repository_specs(raw_manifest, args)
    repositories = load_repositories(specs, args.context)
    mark_iteration_changes(repositories, previous_state)
    manifest = normalize_manifest(raw_manifest, schema_version, repositories)
    report_id = report_identifier(manifest, repositories)
    semantic, warning = resolve_semantic(
        args.config_file,
        token_path=args.token_file,
        config_dir=(
            None
            if args.token_file is not None
            else args.config_file.expanduser().parent
        ),
        repo=repositories[0].root,
    )
    if warning:
        print(f"easy-cr: {warning}; 已生成基础模式 HTML", file=sys.stderr)
    try:
        helper = prepare_report_helper(
            report_id,
            output,
            [repository.root for repository in repositories],
            report_subject=manifest["subject"],
        )
    except (OSError, RuntimeError, ValueError) as error:
        helper = {"mode": "none", "error": str(error)}
        print(
            f"easy-cr: 评论服务不可用：{error}",
            file=sys.stderr,
        )

    repository_payload = {
        repository.id: repository.payload()
        for repository in repositories
    }
    files = [
        (repository, item)
        for repository in repositories
        for item in repository.files
    ]
    added = sum(item.added for _, item in files)
    deleted = sum(item.deleted for _, item in files)
    first = repositories[0]
    report: dict[str, Any] = {
        "schemaVersion": 2,
        "reportId": report_id,
        "commit": report_id,
        "subject": manifest["subject"],
        "files": len(files),
        "added": added,
        "deleted": deleted,
        "repositories": repository_payload,
        "semantic": semantic,
        "helper": helper,
    }
    if len(repositories) == 1:
        report.update({
            "repo": str(first.root),
            "base": first.base,
            "head": first.head,
            "headCommit": first.revision["headCommit"],
            "reviewType": first.revision["reviewType"],
            "fingerprint": first.revision["fingerprint"],
            "context": first.context,
        })
    short_commit = first.revision["headCommit"][:8]
    flow_html = "".join(
        f'<div class="flow-node"><b>{inline_markup(node["title"])}</b>'
        f'{inline_markup(node["detail"])}</div>'
        for node in manifest["flow"]
    )
    checklist = "".join(
        f'<label><input type="checkbox"> {inline_markup(point)}</label>'
        for point in manifest["reviewPoints"]
    )
    diffs = "".join(
        render_file_card(
            item,
            index,
            repository.id,
            repository.label,
        )
        for index, (repository, item) in enumerate(files)
    )
    values = {
        "TITLE": html.escape(f"CR · {manifest['subject']} · {short_commit}"),
        "SUBJECT": inline_markup(manifest["subject"]),
        "SUBTITLE": (
            f"<code>{html.escape(short_commit)}</code> · "
            f"{html.escape(first.author)} · {html.escape(first.authored_at)}"
        ),
        "SCOPE": inline_markup(manifest["scope"]),
        "FILE_COUNT": str(len(files)),
        "REPO_COUNT": str(len(repositories)),
        "ADDED": str(added),
        "DELETED": str(deleted),
        "OVERVIEW_TITLE": inline_markup(manifest["overviewTitle"]),
        "SUMMARY": inline_markup(manifest["summary"]),
        "BOUNDARY": inline_markup(manifest["boundary"]),
        "BUSINESS_FLOW": flow_html,
        "CHECKLIST": checklist,
        "DIFFS": diffs,
        "REPORT_JSON": json_for_script(report),
        "CHAPTER_JSON": json_for_script(manifest["chapters"]),
        "REVIEW_STATE_BLOCK": review_state_block(
            build_review_state(report_id, repositories, previous_state)
        ),
        "COMMENTS_BLOCK": migrate_comments_block(
            previous_html,
            report_id,
            repositories,
        ),
    }
    rendered = replace_template(TEMPLATE_PATH.read_text(), values)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(rendered)
    print(output.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
