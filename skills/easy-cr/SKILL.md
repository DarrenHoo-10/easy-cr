---
name: easy-cr
description: Generate an interactive HTML code review organized from top to bottom by business timeline, with comments, replies, themes, filtering, and optional GoLand/IntelliJ IDEA/VS Code semantic references and navigation. Use when the user wants an easy-to-read CR artifact, wants to review a branch or commit in HTML, or asks to configure the editor used by Easy CR.
---

# Easy CR

Generate one self-contained HTML review. Start from technical-plan chapters, then explain each chapter in business execution order. Put pre-generated explanations beside the smallest complete code unit needed to understand each step.

## Smallest complete code unit

“Smallest” never means the fewest lines. It means the smallest syntactically
closed, independently reviewable unit that expresses one complete business
decision, state change, or external call.

- Prefer one complete function or method.
- For a complete Go function or method, prefer a semantic range such as
  `{"unit_id":"check-reminder","unit_type":"function","symbol":"ShouldTriggerReminder"}`
  and let Easy CR resolve its current start/end lines. Use `Type.Method` when a
  bare method name is not unique.
- Split a function only when every resulting range remains a complete logical
  block, such as a full `if`/`else`, `switch` case, loop, request construction
  plus call and error handling, or a contiguous statement group with a clear
  input and result.
- Never cut through a multi-line function signature, condition expression,
  call argument list, chained expression, struct/object literal, control-flow
  block, or its error-handling path.
- Keep a declaration's leading documentation comment with that declaration.
- One `ranges` entry represents one complete logical unit. When a step needs
  multiple units, use multiple ranges instead of one broad range crossing unit
  boundaries.
- For a logical block inside a long method, provide stable `unit_id`,
  `unit_type` (`block` or `statements`), and explicit `start`/`end`. Reuse the
  same `unit_id` when later business steps refer to that exact unit.
- When the same complete logical unit supports multiple business steps, the
  first step in business order owns and highlights the entire unit. Later steps
  show the entire unit as a gray peer-step change. A single logical unit must
  never be split into partly highlighted and partly gray Diff.
- Before rendering, inspect the first and last line of every range together
  with at least three surrounding lines. Expand, shrink, or split any range
  whose boundary is not syntactically and logically complete.

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

When `easy-cr` is not installed yet, run the bundled cross-platform Python launcher with `node "${SKILL_DIR}/../../scripts/python-runner.js" "${SKILL_DIR}/../../scripts/install_cli.py"` from the plugin source root or use the internal `configure.py` fallback. When the user explicitly asks to view, initialize, diagnose, or change configuration, use `easy-cr status`, `easy-cr init`, `easy-cr doctor`, or `easy-cr config editor`.

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
   - When one file or method supports multiple business steps, divide it only at complete logical-unit boundaries. The first chapter/step that uses a shared unit owns the entire unit; later steps render the entire unit as a gray peer-step change.
   - Write goal, decision, result, explanation, and code annotations while generating the manifest. They are static report content, not browser-time AI output.
   - Put IDL and non-import production changes in the business step they support.
   - Keep test-file diffs out of chapter guidance; they remain available in complete Diff.
   - Dependency files and pure import-only changes stay in complete Diff.
   - Do not create a catch-all “补充其他改动” chapter. If production Diff cannot be mapped to a business chapter, stop and fix the manifest.
6. Create one review directory for this technical plan:
   - Use `.codex-artifacts/YYYY-MM-DD-<manifest subject>/`; `subject` is the actual technical-plan name, so different plans use different directories.
   - Keep its manifest at `manifest.json` and its report at `review.html`.
   - Sanitize path separators and punctuation in the technical-plan title, but keep readable Chinese text.
   - Regenerate feedback rounds into the same directory and `review.html` path so historical comments remain attached.
7. Render:

```bash
node "${SKILL_DIR}/../../scripts/python-runner.js" "${SKILL_DIR}/scripts/build_review.py" \
  --manifest /absolute/path/to/repo/.codex-artifacts/YYYY-MM-DD-技术方案名称/manifest.json
```

The renderer defaults to `.codex-artifacts/YYYY-MM-DD-技术方案名称/review.html`. Pass
`--output` only when regenerating a known historical path or supporting a legacy
workflow. For a legacy v1 manifest, also pass `--repo`, `--base`, and `--head`.

8. Validate:
   - No unresolved `@@TOKEN@@`.
   - Inline JavaScript compiles with `new Function(...)`.
   - Business stages read smoothly from top to bottom.
   - Do not stage or commit review artifacts unless requested.
9. Open the HTML and return a clickable absolute path.
10. The report uses the single Easy CR helper at `127.0.0.1:64346` to persist comments into the current HTML. The top-right `发送评论给 AI` button sends only `pending` comments, marks them `processing`, and resumes the originating Codex/Claude session with the batch id.
11. When an Agent receives an Easy CR comment batch, run:

```bash
easy-cr comments /absolute/path/to/review.html --json
```

Read only comments whose `aiBatchId` matches the batch in the prompt and whose status is `processing`. Do not require the user to copy comments into chat.

Before editing code, classify the whole batch:

- If any comment is a question, discussion, confirmation request, non-code request, or a point the Agent disagrees with, do not change code yet. Present every such item together, wait for the user to confirm, then process the batch as one unit.
- Otherwise implement all actionable comments, validate the result, and regenerate the same report path so historical comments remain attached.
- After the batch is fully handled, including agreed no-code outcomes, reply with the processing result and mark only that batch resolved:

```bash
easy-cr comments /absolute/path/to/review.html --resolve-batch <batch-id> --reply "处理结果：..."
```

Do not mark a batch resolved before implementation, validation, and report regeneration are complete. The reply should state what changed, what was confirmed as no-code, or why no change was needed.

The executable persistence, batch, regeneration, and failure contracts are defined in [references/review-lifecycle.md](references/review-lifecycle.md).

## Interaction contract

The base HTML always supports:

- Chapter overview, guided step-by-step review, and complete Diff.
- Pre-generated goal, decision, result, explanation, and code annotations.
- Diff filtering, search and folding.
- Dark/light themes.
- Document, chapter, selected-code and line comments.
- Selecting code leaves the original browser selection unchanged and highlights only other exact repeated text on the current page. The repeated-text highlights clear as soon as the selection is cancelled. Right-click exposes `评论` and `不懂就问`, including selections that cross the line-number gutter.
- Selecting text inside a `不懂就问` conversation exposes only `添加到任务`. It opens a compact annotation input beside the selection: Enter saves and closes it, Command/Ctrl+Enter and Shift+Enter insert newlines, and Escape cancels. Saved annotations use persistent Codex-style blue comment-bubble numbers at the source text; clicking a number reopens that annotation for editing, and adding another annotation does not hide existing numbers. The matching Q&A composer summarizes them with an `N 条注释` chip whose hover card shows selected text and user notes. The existing `不懂就问` send action submits annotations with the current question while rendering only the count chip and question body, not expanded annotation details. Source numbers and the composer chip clear immediately when the request starts. A failed request keeps the compact sent message and exposes a retry action. Saving never sends, never wakes the report-generating task, and never creates or mutates report comments.
- Selected-code `不懂就问` opens an inline code Q&A box below the code. The reviewer asks the first question before any request is sent and can continue with follow-up questions; answers stream in place. One technical-plan directory reuses one read-only explanation session, and questions for that plan are processed FIFO. The page keeps a separate visible Q&A history for each selected code location in browser session storage keyed by `reportId`, so switching locations does not mix their panels and a refresh restores them; regenerated reports do not migrate the browser state. The left caret toggles collapse state and there is no close action.
- Comment edit, delete, reply, resolve, summary popover and copy.
- Persistence into the current HTML through the single local Easy CR helper, with a local pending draft while the service is unavailable.
- No reviewed-copy export and no browser file picker.
- Comment status follows `未处理 → 处理中 → 已解决`; edit, reply, or reopen returns a comment to `未处理`.
- When an Agent resolves a sent batch, it writes an AI reply on each resolved comment with the processing result.
- A top-right `发送评论给 AI` action sends only unprocessed comments. It shows a green success check briefly after synchronous acceptance.
- Regeneration preserves historical comments. Exact anchors are retained when possible; otherwise code comments move near matching code in the same file. Deleted files safely no-op.
- Previously reviewed additions use light green, current feedback changes use deep green, and deletions use light red.
- The report header explains all code colors: additions, feedback changes, deletions, peer-step changes, and comment locations.
- A complete logical unit is highlighted as the current change in at most one business step. If multiple steps use it, the first step in business order owns the entire unit and every later step renders the entire unit as a gray peer-step change; the unit is never split into mixed current/peer colors and report generation continues normally.
- Previous and next navigation both name their destination; the outer edges return to the chapter overview.
- `Enter` saves; `Command/Ctrl+Enter` and `Shift+Enter` insert a newline.

When an enhanced editor is configured:

- Only Command+click (macOS) or Ctrl+click (Windows) on eligible identifiers requests references.
- With no references, the editor opens the clicked source position.
- With one reference, the editor opens that call location directly.
- With multiple references, HTML keeps focus and shows a choice list; clicking one opens its actual call location in the editor.
- Loading, empty and error states stay in the reference popover; there is no bottom-right semantic toast.

When no editor is configured, the page contains no editor token or endpoint and does not issue semantic requests.

## Boundaries

- Enhanced editors are selected from the built-in registry: `goland`, `idea`, and `vscode`.
- Do not start `gopls`, MCP, or per-report background processes. All reports reuse the one LaunchAgent-managed Easy CR helper.
- Browser-time AI is limited to selected-code Q&A through the local helper; it must not modify files or comment state. Business-step explanations are still generated before the HTML is written.
- Do not infer online behavior from code alone.
- Do not organize the main review by technical layer or directory.
- Keep precise same-page semantic identifier highlighting on hold unless the user explicitly reopens that scope.
