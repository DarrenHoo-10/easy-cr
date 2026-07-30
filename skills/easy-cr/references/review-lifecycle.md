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
- Selected-code `不懂就问` uses the same registered report token. The first request contains the selected code and the reviewer's question; later requests may include the bounded in-page question history. Answers stream below the selected code with a left caret collapse toggle, and do not write comments, change statuses, or modify files.
- Report regeneration on the same path preserves comment ids, replies, timestamps, status, and batch metadata while updating `reportId`.
- Exact code anchors are preferred. A failed exact match may move only within the same repository and file and must set `target.approximate=true`.
- Every changed production line except tests, dependency files, and conservatively recognized import-only changes must be visible in a business chapter.

## 4. Validation & Error Matrix

| Condition | Result |
|---|---|
| Expected revision is stale | HTTP 409; no comments are overwritten |
| Any sent comment is missing or not pending | Request rejected; Agent is not started |
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
