---
name: easy-cr
description: Generate an interactive HTML code review organized from top to bottom by business timeline, with comments, replies, themes, filtering, and optional GoLand semantic references and navigation. Use when the user wants an easy-to-read CR artifact, wants to review a branch or commit in HTML, or asks to configure the editor used by Easy CR.
---

# Easy CR

Generate one self-contained HTML review. Start from technical-plan chapters, then explain each chapter in business execution order. Put pre-generated explanations beside the smallest complete code unit needed to understand each step.

## First-use editor choice

Before the first review, inspect the shared configuration:

```bash
easy-cr status --json
```

When `editor.configured` is `null`, ask once:

> 是否启用 GoLand 联动？启用后可在评审页查看语义引用并快速跳转代码。

- If accepted, run `easy-cr config editor goland`.
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
4. Trace the change as technical-plan chapters and a business timeline, not as a directory list:
   - Identify the trigger/input.
   - Follow key decisions in execution order.
   - Describe state or data changes.
   - End with the externally visible result.
5. Create a manifest following [references/manifest-schema.md](references/manifest-schema.md):
   - Prefer schema v2 and model repositories, chapters, steps, and code ranges explicitly.
   - Keep `flow` to 3–6 nodes and order chapters/steps by business execution.
   - One chapter may reference code from multiple repositories; generate one report, not one report per repository.
   - Write goal, decision, result, explanation, and code annotations while generating the manifest. They are static report content, not browser-time AI output.
   - Put IDL and non-import production changes in the business step they support.
   - Keep test-file diffs out of chapter guidance; they remain available in complete Diff.
   - Dependency files and pure import-only changes stay in complete Diff.
   - Do not create a catch-all “补充其他改动” chapter. If production Diff cannot be mapped to a business chapter, stop and fix the manifest.
6. Render:

```bash
python3 "${SKILL_DIR}/scripts/build_review.py" \
  --manifest /absolute/path/to/review-manifest.json \
  --output /absolute/path/to/repo/.codex-artifacts/review-<short-id>.html
```

For a legacy v1 manifest, also pass `--repo`, `--base`, and `--head`.

7. Validate:
   - No unresolved `@@TOKEN@@`.
   - Inline JavaScript compiles with `new Function(...)`.
   - Business stages read smoothly from top to bottom.
   - Do not stage or commit review artifacts unless requested.
8. Open the HTML and return a clickable absolute path.
9. The report uses the single Easy CR helper at `127.0.0.1:64344` to persist comments into the current HTML. The top-right `发送评论给 AI` button sends only `pending` comments, marks them `processing`, and resumes the originating Codex/Claude session with the batch id.
10. When an Agent receives an Easy CR comment batch, run:

```bash
easy-cr comments /absolute/path/to/review.html --json
```

Read only comments whose `aiBatchId` matches the batch in the prompt and whose status is `processing`. Do not require the user to copy comments into chat.

Before editing code, classify the whole batch:

- If any comment is a question, discussion, confirmation request, non-code request, or a point the Agent disagrees with, do not change code yet. Present every such item together, wait for the user to confirm, then process the batch as one unit.
- Otherwise implement all actionable comments, validate the result, and regenerate the same report path so historical comments remain attached.
- After the batch is fully handled, including agreed no-code outcomes, mark only that batch resolved:

```bash
easy-cr comments /absolute/path/to/review.html --resolve-batch <batch-id>
```

Do not mark a batch resolved before implementation, validation, and report regeneration are complete.

The executable persistence, batch, regeneration, and failure contracts are defined in [references/review-lifecycle.md](references/review-lifecycle.md).

## Interaction contract

The base HTML always supports:

- Chapter overview, guided step-by-step review, and complete Diff.
- Pre-generated goal, decision, result, explanation, and code annotations.
- Diff filtering, search and folding.
- Dark/light themes.
- Document, chapter, selected-text and line comments.
- Left-selection and right-click comments, including selections that cross the line-number gutter.
- Comment edit, delete, reply, resolve, summary popover and copy.
- Persistence into the current HTML through the single local Easy CR helper, with a local pending draft while the service is unavailable.
- No reviewed-copy export and no browser file picker.
- Comment status follows `未处理 → 处理中 → 已解决`; edit, reply, or reopen returns a comment to `未处理`.
- A top-right `发送评论给 AI` action sends only unprocessed comments. It shows a green success check briefly after synchronous acceptance.
- Regeneration preserves historical comments. Exact anchors are retained when possible; otherwise code comments move near matching code in the same file. Deleted files safely no-op.
- Previously reviewed additions use light green, current feedback changes use deep green, and deletions use light red.
- Previous and next navigation both name their destination; the outer edges return to the chapter overview.
- `Enter` saves; `Command+Enter` and `Shift+Enter` insert a newline.

When GoLand is configured:

- Only Command+click on eligible Go identifiers requests references.
- With no references, GoLand opens the clicked source position.
- With one reference, GoLand opens that call location directly.
- With multiple references, HTML keeps focus and shows a choice list; clicking one opens its actual call location in GoLand.
- Loading, empty and error states stay in the reference popover; there is no bottom-right semantic toast.

When no editor is configured, the page contains no editor token or endpoint and does not issue semantic requests.

## Boundaries

- GoLand is the only enhanced editor in the first version.
- Do not start `gopls`, MCP, or per-report background processes. All reports reuse the one LaunchAgent-managed Easy CR helper.
- Do not add browser-time AI calls; all explanations are generated before the HTML is written.
- Do not infer online behavior from code alone.
- Do not organize the main review by technical layer or directory.
- Keep precise same-page semantic identifier highlighting on hold unless the user explicitly reopens that scope.
