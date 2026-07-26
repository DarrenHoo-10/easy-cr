---
name: easy-cr
description: Generate an interactive HTML code review organized from top to bottom by business timeline, with comments, replies, themes, filtering, and optional GoLand/IntelliJ IDEA/VS Code semantic references and navigation. Use when the user wants an easy-to-read CR artifact, wants to review a branch or commit in HTML, or asks to configure the editor used by Easy CR.
---

# Easy CR

Generate one self-contained HTML review. Explain the business flow first, then place each relevant Diff directly under the business stage it implements.

## First-use editor choice

Before the first review, inspect the shared configuration:

```bash
easy-cr status --json
```

When `editor.configured` is `null`, ask once:

> 是否启用编辑器联动？可选择 GoLand、IntelliJ IDEA、VS Code，或保持基础模式。启用后可在评审页查看语义引用并快速跳转代码。

- If the user chooses GoLand, run `easy-cr config editor goland`.
- If the user chooses IntelliJ IDEA, run `easy-cr config editor idea`.
- If the user chooses VS Code, run `easy-cr config editor vscode`.
- If declined or deferred, run `easy-cr config editor none`.
- Do not ask again after either choice is stored.

When `easy-cr` is not installed yet, run `python3 "${SKILL_DIR}/../../scripts/install_cli.py"` from the plugin source root or use the internal `configure.py` fallback. When the user explicitly asks to view, initialize, diagnose, or change configuration, use `easy-cr status`, `easy-cr init`, `easy-cr doctor`, or `easy-cr config editor`.

## Review workflow

1. Read repository instructions and inspect `git status`; preserve unrelated changes.
2. Resolve the exact review range:
   - Use revisions named by the user.
   - For the latest commit, use `HEAD^` → `HEAD`.
   - For a feature branch, prefer its merge base with the intended base.
   - Use `WORKTREE` only for tracked uncommitted changes; untracked files are excluded.
3. Inspect diff stats, changed files and the relevant patch.
4. Trace the change as a business timeline, not as a directory list:
   - Identify the trigger/input.
   - Follow key decisions in execution order.
   - Describe state or data changes.
   - End with the externally visible result.
5. Create a manifest following [references/manifest-schema.md](references/manifest-schema.md):
   - Keep `flow` to 3–6 nodes.
   - Order `groups` in the same top-to-bottom business sequence.
   - Put tests, IDL and dependency changes in the stage they support.
   - Use “其他改动” only when a changed file genuinely cannot join the main flow.
6. Render:

```bash
python3 "${SKILL_DIR}/scripts/build_review.py" \
  --repo /absolute/path/to/repo \
  --base <base-revision> \
  --head <head-revision-or-WORKTREE> \
  --manifest /absolute/path/to/review-manifest.json \
  --output /absolute/path/to/repo/.codex-artifacts/review-<short-id>.html
```

7. Validate:
   - No unresolved `@@TOKEN@@`.
   - Inline JavaScript compiles with `new Function(...)`.
   - Business stages read smoothly from top to bottom.
   - Do not stage or commit review artifacts unless requested.
8. Open the HTML and return a clickable absolute path.

## Interaction contract

The base HTML always supports:

- Business timeline and stage explanations.
- Diff filtering, search and folding.
- Dark/light themes.
- Text selection comments and line comments.
- Comment edit, delete, reply, summary popover and copy.
- `Enter` saves; `Command+Enter` and `Shift+Enter` insert a newline.

When an enhanced editor is configured:

- Command+click on added/context source lines sends a position request (`filePath + line + UTF-8 byte column`).
- With no references, the editor opens the clicked source position.
- With one reference, the editor opens that call location directly.
- With multiple references, HTML keeps focus and shows a choice list; clicking one opens its actual call location in the editor.
- Loading, empty and error states stay in the reference popover; there is no bottom-right semantic toast.

When no editor is configured, the page contains no editor token or endpoint and does not issue semantic requests.

## Boundaries

- Enhanced editors are selected from the built-in registry: `goland`, `idea`, and `vscode`.
- Do not start `gopls`, a Python helper, MCP, or another background service outside the installed editor extension.
- Do not infer online behavior from code alone.
- Do not organize the main review by technical layer or directory.
