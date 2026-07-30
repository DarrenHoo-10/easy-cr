# Easy CR manifest

优先使用 schema v2。它用“技术方案章节 → 业务步骤 → 代码范围”组织评审，并允许一个章节连续讲解多个仓库。

```json
{
  "schema_version": 2,
  "subject": "任务回显与自动提交业务方案",
  "scope": "任务服务、方案服务和补偿任务的一条完整业务链路",
  "overview_title": "改动概括",
  "summary": "创建或修改任务后同步订单配置，并自动提交未提交的业务方案。",
  "boundary": "已确认方案的订单不再同步任务备注和预览图。",
  "repositories": [
    {
      "id": "task-service",
      "label": "service_a",
      "root": "/absolute/path/to/service_a",
      "base": "origin/master",
      "head": "HEAD",
      "context": 10
    },
    {
      "id": "proposal-service",
      "label": "service_b",
      "root": "/absolute/path/to/service_b",
      "base": "origin/master",
      "head": "HEAD"
    }
  ],
  "flow": [
    {"title": "保存任务", "detail": "写入任务与订单配置"},
    {"title": "判断是否提交", "detail": "仅处理尚未提交方案的订单"},
    {"title": "完成提交", "detail": "提交成功或展示失败处理"}
  ],
  "review_points": [
    "订单确认后是否停止同步",
    "多任务配置是否按 task_id 隔离",
    "自动提交失败分支是否完整"
  ],
  "chapters": [
    {
      "id": "auto-submit",
      "title": "任务回显与自动提交业务方案",
      "goal": "从任务保存自然讲到业务方案提交结果。",
      "summary": "同一章节可以引用多个仓库的代码。",
      "points": ["数据映射", "提交条件", "失败处理"],
      "steps": [
        {
          "id": "save-task",
          "title": "保存任务配置",
          "goal": "持久化任务备注和预览图。",
          "decision": "订单方案未确认时才同步订单。",
          "result": "订单保存 mission_id 到任务配置的映射。",
          "explanation": "这一段解释在生成 HTML 时写入，浏览器不调用 AI。",
          "code": [
            {
              "repo_id": "task-service",
              "path": "service/mission/save.go",
              "ranges": [{
                "unit_id": "save-task",
                "unit_type": "function",
                "symbol": "SaveTask"
              }],
              "display_mode": "guided",
              "annotation": "任务与订单更新在同一事务内完成。"
            }
          ]
        },
        {
          "id": "submit-proposal",
          "title": "自动提交业务方案",
          "explanation": "先查询订单是否已提交；只有未提交时才发起自动提交。",
          "code": [
            {
              "repo_id": "proposal-service",
              "path": "service/commission/submit.go",
              "display_mode": "compact-context"
            }
          ]
        }
      ]
    }
  ]
}
```

## 字段规则

- `repositories[].id`、`chapters[].id`、`steps[].id` 必须稳定且唯一。
- `root` 必须是绝对 Git 仓库路径；每个仓库独立指定 `base` 和 `head`。
- `head` 可以使用 revision，也可以使用 `WORKTREE`；后者只包含已跟踪的工作区改动。
- `code[].repo_id + path` 必须指向对应仓库在本次 Diff 中发生变化的文件。
- `ranges` 可省略；填写时必须覆盖该文件应归入本步骤的全部业务 Diff。
- 完整 Go 函数或方法优先使用语义范围：`unit_id` 是稳定逻辑单元标识，`unit_type` 填 `function`，`symbol` 填函数名或 `Type.Method`；Easy CR 根据受评版本源码自动解析 `start/end`，避免手写行号跨入相邻方法。
- 长方法内部拆分时，使用 `unit_type: block` 或 `unit_type: statements`，同时填写稳定的 `unit_id` 和显式 `start/end`。后续步骤复用同一逻辑单元时必须复用相同 `unit_id`。
- 兼容旧格式 `{"start": 120, "end": 155}`，其 `unit_type` 默认为 `range`；新建或修改报告时应优先补充逻辑单元信息。
- `ranges` 的最小粒度是“完整逻辑单元”，不是最少行数。默认使用完整函数或方法；只有方法内部确实包含多个独立业务动作时，才可按完整的条件块、分支、循环、请求构造与调用及错误处理、或具备明确输入与结果的连续语句组拆分。
- 范围边界不得切断多行函数签名、条件表达式、调用参数、链式表达式、结构体/对象构造、控制流代码块或对应错误处理；声明注释应与声明保持在同一范围。
- 一个 `ranges` 条目只表示一个完整逻辑单元；同一步骤需要多个单元时应填写多个范围，不得使用跨越多个无关逻辑单元的宽范围。
- 同一完整逻辑单元可以被多个业务步骤引用，但必须整体归属：按章节和步骤的业务顺序由第一个步骤完整高亮，后续步骤将整个单元置灰，不得在同一逻辑单元内部出现部分高亮、部分置灰，也不阻断报告生成。
- 多个步骤可以共享未修改的上下文行；上述首次归属规则只作用于新增、删除 Diff。
- `display_mode` 可选：
  - `guided`：突出指定范围，适合主业务逻辑。
  - `compact-context`：展示必要上下文，适合一般实现。
  - `diff-only`：只展示改动行，适合依赖、生成物和 import-only 改动。
- 未显式指定展示模式时，依赖清单、锁文件、生成物和 import-only 改动自动使用 `diff-only`，其他文件使用 `compact-context`。
- `goal`、`decision`、`result`、`explanation` 和 `annotation` 都在生成报告时预先写入；HTML 内没有运行时 AI 请求。
- 除测试文件、依赖文件和纯 import-only 改动外，每一行生产代码 Diff 都必须被业务章节引用；文件未归类或 `ranges` 遗漏业务改动时，生成器会直接报错。

## 内容组织规则

- 章节对应技术方案中的业务功能，不按目录或 API/Service/DAO 技术层拆分。
- 步骤按实际发生顺序排列，从业务触发、判断和状态变化讲到最终结果。
- 同一章节可以连续引用多个仓库；不要为每个仓库单独生成一份报告。
- IDL、依赖改动应放进其支撑的业务步骤。
- 测试文件无需写入章节代码引用；生成器会将其保留在“完整 Diff”的测试分组中，不在章节讲解区展示。
- 依赖文件和纯 import-only 改动保留在“完整 Diff”的“测试与依赖”分组，不创建兜底业务章节。
- 不使用“补充其他改动”。无法归入现有章节的生产代码应先调整技术方案结构，再生成报告。
- `flow` 建议保留 3–6 个节点；省略时会从章节自动生成。
- 每次 CR 使用独立目录：`.codex-artifacts/YYYY-MM-DD-技术方案名称/`。技术方案名称取当前 manifest 的 `subject`，所以不同方案会进入不同目录。目录内保存 `manifest.json` 和 `review.html`，同一轮评论后的重新生成继续复用该目录和报告路径。
- 未传 `--output` 时，生成器会根据第一个受评仓库、当前日期和 `subject` 自动写入上述 `review.html`；显式 `--output` 仍用于历史报告和兼容场景。
- 报告输出路径应位于任一受评仓库的 `.codex-artifacts` 目录。生成器会向单实例 Easy CR helper 注册该报告，评论只写回这一个 HTML。

## v1 兼容

旧版单仓库 manifest 仍可继续使用 `groups`，并通过命令行传入 `--repo --base --head`。生成器会把它归一化成单仓库 v2 页面；新报告不再建议使用 v1。
