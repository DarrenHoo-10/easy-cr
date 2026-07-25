# Easy CR 多编辑器支持实施计划

## Phase 1：编辑器无关协议

- [ ] 为 `none|goland|idea|vscode` 建立不可变 editor registry。
- [ ] 保留 64343 和旧 token 路径，新增 IDEA/VS Code 固定 endpoint。
- [ ] 将 semantic HTML 配置升级为 editor-neutral schema，并兼容旧 `mode=goland`。
- [ ] 移除 Go-only highlighting/identifier span，改为 Command+点击位置计算。
- [ ] `/api/references` 改为位置驱动，symbol 由 adapter 返回。
- [ ] 定义统一错误码、health schema 和 protocolVersion。
- [ ] 增加 config、HTML 点击列换算、旧配置兼容和 endpoint 固定性测试。

## Phase 2：JetBrains Adapter

- [ ] 将现有 GoLand 插件整理为共用 JetBrains 插件源码。
- [ ] 用通用 PSI reference 解析替换 `GoReferencesSearch` 和 `.go` 文件限制。
- [ ] 通过构建资源注入 GoLand/IDEA 的 editorId 与端口。
- [ ] 新增统一 JetBrains 构建安装脚本，支持应用和插件目录检测。
- [ ] 分别构建、安装并验证 GoLand 与 IntelliJ IDEA。
- [ ] 覆盖 provider 可用/不可用、0/1/N 引用、仓库外引用过滤、打开与聚焦测试。

## Phase 3：VS Code Adapter

- [ ] 初始化零运行时第三方依赖或最小依赖的 TypeScript VS Code extension。
- [ ] 实现 loopback HTTP、CORS、token、body limit 和统一协议。
- [ ] 实现 workspace/project 匹配与 Git revision/worktree fingerprint 校验。
- [ ] 实现 UTF-8 byte column 到 VS Code UTF-16 Position 的转换。
- [ ] 接入 `vscode.executeReferenceProvider`、结果过滤和预览。
- [ ] 实现打开文件、定位、reveal 与窗口激活。
- [ ] 实现 `.vsix` 构建和 `code --install-extension --force` 安装。
- [ ] 覆盖 server 安全、provider 结果、0/1/N 引用和跳转测试。

## Phase 4：CLI、诊断与文档

- [ ] 将配置、安装、status 和 doctor 重构为 editor registry 驱动。
- [ ] 增加 IDEA/VS Code 应用、安装器、adapter 和 runtime 状态。
- [ ] health 校验 editor 与 protocolVersion。
- [ ] 更新交互选择、非交互参数和错误提示。
- [ ] 更新 README、SKILL 与配置参考。
- [ ] 更新 Codex/Claude 插件版本并执行幂等安装验证。

## 验证矩阵

| 场景 | none | GoLand | IDEA | VS Code |
|---|---:|---:|---:|---:|
| HTML 生成 | ✓ | ✓ | ✓ | ✓ |
| 无 token/endpoint 泄露 | ✓ | ✓ | ✓ | ✓ |
| 新增/上下文行点击 | N/A | ✓ | ✓ | ✓ |
| 删除/meta 行拒绝 | N/A | ✓ | ✓ | ✓ |
| 0/1/N 引用 | N/A | ✓ | ✓ | ✓ |
| 仓库外引用过滤 | N/A | ✓ | ✓ | ✓ |
| 过期 fingerprint 拒绝 | N/A | ✓ | ✓ | ✓ |
| 无 provider 明确报错 | N/A | ✓ | ✓ | ✓ |
| 定位并激活编辑器 | N/A | ✓ | ✓ | ✓ |
| status/doctor | ✓ | ✓ | ✓ | ✓ |

## 建议实施顺序

建议拆成三个可独立评审的提交：

1. `refactor: make Easy CR editor protocol position based`
2. `feat: support IntelliJ IDEA adapter`
3. `feat: support Visual Studio Code adapter`

IDEA 与 VS Code 都依赖第一个提交；二者之后可以独立开发和验证。

## 风险与回滚点

- **HTML 点击列偏移**：先完成 UTF-8/UTF-16、中文、emoji、tab 和 Diff 前缀测试，再修改 adapter。
- **JetBrains API 兼容**：使用目标 IDE JBR 构建，并对 GoLand/IDEA 两个目标运行 Plugin Verifier。
- **VS Code 激活行为**：先验证已打开应用从浏览器切换的实际体验；无法稳定激活时保留已定位状态并给出明确提示。
- **配置迁移**：不更改旧 token 路径和 GoLand 端口；任一阶段失败均可切回 `none`。
- **协议不一致**：以共享 JSON fixtures 对 Java、TypeScript 和 HTML 做契约测试。

## 完成门槛

- PRD、design 与 implement 通过用户评审后，才执行 `task.py start`。
- 实施前读取 Trellis coding specs，并为三阶段分别执行测试先行。
- 所有 editor 的安全校验和旧 GoLand 回归通过后才能发布。
