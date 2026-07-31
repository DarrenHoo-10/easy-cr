# Easy CR review lifecycle contract

## 1. Scope / Trigger

This contract applies when a generated report persists human comments, sends a comment batch to its originating Agent, or regenerates the same output path after feedback.

## 2. Signatures

```text
POST /api/comments/write
POST /api/explain
POST /api/reviews/complete
easy-cr comments <report> --json
easy-cr comments <report> --resolve-batch <batch-id> --reply <result>
```

`/api/reviews/complete` accepts:

```json
{
  "reportId": "report-id",
  "revision": 3,
  "commentIds": ["comment-1", "comment-2"],
  "aiBatchId": "ai-batch-id"
}
```

## 3. Contracts

- Comment status is exactly `pending`, `processing`, or `resolved`.
- New, edited, replied-to, or reopened comments are `pending`.
- A successful send changes only the requested pending comments to `processing` and writes their `aiBatchId`.
- Agent completion replies to each matching processing comment with the handling result, then changes only those comments to `resolved`.
- Selected-code comments keep the existing comment persistence and status lifecycle. `添加到任务` is available only for text selected inside `不懂就问` conversations and opens a compact annotation input beside the selection. Enter saves and closes the input, Command+Enter and Shift+Enter insert newlines, and Escape cancels. Saved annotations stay in browser session storage, use clickable Codex-style blue comment-bubble numbers at their source text, and are summarized by an `N 条注释` chip in the matching Q&A composer; hovering the chip shows the selected text and user comment. The existing Q&A send action submits the annotations with the current question through `POST /api/explain`; the visible message renders only the count chip and question body. Source numbers and the composer chip clear as soon as the request starts. On failure the compact message remains with a retry action. It never resumes the report-generating task, writes report comments, or changes comment status.
- Comments and selected-code Q&A created in an explicit business review section store optional `target.sectionId`. Navigation restores that section before locating the code anchor. Historical targets without `sectionId` continue to resolve to their step and then the first section containing the file.
- Selected-code `不懂就问` uses the same registered report token. One technical-plan directory owns one read-only explanation session forked from the report-generating Agent; all questions for that plan enter a FIFO queue, while different plans use independent queues. The first request contains the selected code and the reviewer's question; later requests may include the bounded history for that code location as a recovery hint. The current report keeps separate completed Q&A turns, unsent input, target, view, and collapse state for each selected code location in browser session storage keyed by `reportId`, so switching locations does not mix their panels and refreshing the same page restores them; report regeneration does not migrate this browser state. Answers stream below the selected code with a left caret collapse toggle, and do not write comments, change statuses, or modify files.
- Report regeneration on the same path preserves comment ids, replies, timestamps, status, and batch metadata while updating `reportId`.
- Exact code anchors are preferred. A failed exact match may move only within the same repository and file and must set `target.approximate=true`.
- Every changed production line except tests, dependency files, and conservatively recognized import-only changes must be visible in a business chapter.

## 4. Validation & Error Matrix

| Condition | Result |
|---|---|
| Expected revision is stale | HTTP 409; no comments are overwritten |
| Any sent comment is missing or not pending | Request rejected; Agent is not started |
| Task instruction is empty, or annotations are missing/over limit | HTTP 400; Agent is not started |
| Q&A request has no selected code or question | HTTP 400; no comments are changed |
| Agent launch fails | Comment HTML rolls back to pending |
| Batch has no processing comments | `--resolve-batch` fails without changing the report |
| Production file is not in a chapter | Report generation fails with repo and path |
| Guided ranges omit a business line | Report generation fails with repo, path, and line |
| Historical target file is absent | Comment remains in summary; navigation no-ops |

## 5. Good / Base / Bad Cases

- Good: persist comments, send one pending batch, process and validate it, regenerate the same report, reply with the result, then resolve that batch.
- Base: open or regenerate a report without comments; the report remains usable and no batch is sent.
- Bad: resend processing comments, resolve before validation, silently place unclassified code in a catch-all chapter, or move a historical comment across files.

## 6. Tests Required

- Legacy `resolved` booleans migrate to the three-state schema.
- Send success, duplicate send, stale revision, and Agent launch rollback.
- Batch resolution replies to and changes only matching processing comments.
- Two- and three-round generation verifies deep-green current changes and light-green unchanged reviewed lines.
- Comment ids and status survive regeneration; line drift produces an approximate same-file anchor.
- Unlisted files and omitted ranges fail; deletion lines are covered; import/test/dependency exemptions remain in complete Diff.
- Inline JavaScript compiles and plugin manifests validate.

## 7. Wrong vs Correct

Wrong:

```text
send every unresolved comment -> start Agent -> reset the entire report to resolved
```

Correct:

```text
persist pending comments -> send explicit batch -> mark that batch processing
-> Agent confirms/implements/verifies -> regenerate same path
-> reply with result -> resolve that batch
```
