# Easy CR manifest

Create one UTF-8 JSON manifest:

```json
{
  "subject": "可选：覆盖提交标题",
  "scope": "当前分支相对目标基线的代码改动；不包含未跟踪文件",
  "overview_title": "改动概括",
  "summary": "先说明业务目标，再说明最终变化。标识符可使用 `backticks`。",
  "boundary": "说明生效范围、兼容边界和明确不受影响的流程。",
  "flow": [
    {"title": "接收请求", "detail": "读取业务输入"},
    {"title": "执行判断", "detail": "校验条件并决定分支"},
    {"title": "完成处理", "detail": "写入结果或返回响应"}
  ],
  "review_points": [
    "生效范围是否准确",
    "状态或数据变化是否完整",
    "失败路径是否清晰"
  ],
  "groups": [
    {
      "id": "receive-request",
      "title": "接收业务请求",
      "summary": "说明本阶段输入、目标和输出。",
      "points": ["入口", "参数", "边界"],
      "files": ["handler.go", "service/example.go"]
    },
    {
      "id": "verify-behavior",
      "title": "验证业务结果",
      "summary": "说明测试如何覆盖主线与异常分支。",
      "points": ["主流程", "异常流程"],
      "files": ["service/example_test.go"]
    }
  ]
}
```

## Rules

- `flow` 必须包含 3–6 个按发生顺序排列的业务节点。
- `groups` 顺序就是页面从上到下的业务时序。
- 每个阶段先解释业务输入、判断和结果，再展示对应 Diff。
- 测试、IDL、依赖改动应归入其服务的业务阶段。
- 同一文件最多属于一个阶段。
- group 标题使用业务动作，不使用“API 层”“Service 层”等纯技术分层。
- 不得引用本次 Diff 之外的文件。
- 不写入原始 HTML。

## Editor protocol (v2)

Semantic navigation is independent of the manifest. Generated HTML embeds an editor-neutral payload from the shared config, then sends position requests:

```json
{
  "token": "...",
  "projectPath": "/absolute/repo",
  "reviewType": "revision",
  "fingerprint": "...",
  "base": "HEAD^",
  "context": 10,
  "filePath": "service/example.go",
  "line": 42,
  "column": 18
}
```

- `line` is 1-based.
- `column` is a 1-based UTF-8 byte offset into the displayed source line after the leading Diff marker.
- HTML does not infer or send a symbol name; the editor adapter resolves the PSI/LSP target.
- Compatible responses may include an optional `symbol` plus `opened` and `references`.
