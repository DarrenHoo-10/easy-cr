# Easy CR VS Code Implementation Plan

> 实施时使用 executing-plans 工作流；开始前确认 IDEA 子任务的 protocol v2 已冻结。

## Task 1：初始化 VS Code extension

- [x] 创建 extension manifest、TypeScript、esbuild、VSIX 和测试配置。
- [x] 添加 activation/deactivation smoke test。
- [x] 运行 extension test，确认测试先失败再实现最小入口。
- [x] 提交：`feat: scaffold VS Code adapter`

## Task 2：实现位置和协议模型

- [x] 为 ASCII、中文、emoji、tab 和越界列写失败测试。
- [x] 实现 UTF-8 byte column 到 UTF-16 Position 的转换。
- [x] 从 IDEA 子任务共享 fixture 验证 Java 与 TypeScript 结果一致。
- [x] 定义 protocol v2 TypeScript types 和稳定错误码。
- [x] 提交：`feat: add VS Code protocol model`

## Task 3：实现 loopback server 安全边界

- [x] 为 bind address、method、origin、content type、body limit 和 token 写失败测试。
- [x] 实现固定 `127.0.0.1:64345` server。
- [x] 添加 health 的 editor 和 protocolVersion。
- [x] 确保 deactivate 关闭 server 和未完成请求。
- [x] 提交：`feat: add secure VS Code bridge`

## Task 4：实现 workspace 与 review 校验

- [x] 为单 workspace、多 root、仓库外路径、symlink escape 和未打开项目写测试。
- [x] 复刻并对齐 JetBrains Adapter 的 Git fingerprint 校验。
- [x] 每个请求重新校验 project、revision 和路径。
- [x] 检测 `vscode.env.remoteName` 并返回 unsupported。
- [x] 提交：`feat: validate VS Code review context`

## Task 5：接入 references 和 open

- [x] mock `vscode.executeReferenceProvider` 覆盖 0/1/N、重复、仓库外和超过 500 条结果。
- [x] 实现 preview、排序、去重和结果过滤。
- [x] 实现 `openTextDocument`、`showTextDocument`、selection 和 revealRange。
- [x] 对 provider 空数组执行零引用行为，不伪造 provider availability。
- [x] 提交：`feat: add VS Code semantic navigation`

## Task 6：CLI 安装与诊断

- [x] 在 editor registry 增加 vscode descriptor、端口和 token。
- [x] 创建 VSIX build/install 脚本。
- [x] 添加 code 命令检测、幂等强制安装、扩展缺失和 runtime health 测试。
- [x] 更新 init、config、status 和 doctor。
- [x] 提交：`feat: install and diagnose VS Code adapter`

## Task 7：集成验证与发布资源

- [x] 使用 TypeScript/JavaScript 内置 provider 验证 0/1/N。
- [x] 安装 Go 扩展后验证 Go provider。
- [x] 验证焦点切换；不可靠时启用显式 `vscode://file` 降级。
- [x] 构建并从 VSIX 安装到干净 VS Code profile。
- [x] 更新 npm files 白名单和 tarball 安装测试。
- [x] 更新 README、SKILL 和配置参考。
- [x] 运行 `npm test`、extension tests、`vsce package` 和 `npm pack --dry-run`。
- [x] 提交：`docs: document VS Code support`

## Completion Gate

- 所有 Acceptance Criteria 通过。
- GoLand 和 IDEA adapter 回归测试继续通过。
- VSIX 不包含源码、测试、node_modules 或 token。
- 父任务的验证矩阵更新为实际结果。
