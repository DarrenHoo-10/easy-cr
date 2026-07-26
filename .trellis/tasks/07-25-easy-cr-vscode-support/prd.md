# Easy CR Visual Studio Code Adapter

## Goal

为 VS Code Desktop 本地 workspace 提供与 GoLand、IDEA 一致的 Easy CR 语义引用和代码跳转体验，不启动额外语言服务器。

## Dependency

必须先完成 `07-25-easy-cr-intellij-idea-support` 中的 editor-neutral protocol v2、HTML 位置驱动点击和 editor registry 基础。

## User Stories

- 用户执行 `easy-cr config editor vscode` 后，CLI 构建并安装 Easy CR VSIX。
- 用户在 HTML 中 Command+点击符号，Easy CR 调用当前语言扩展注册的 reference provider。
- 0 个引用时打开当前位置，1 个引用时直接打开引用位置，多个引用时由 HTML 展示选择列表。
- 未安装 `code` 命令、扩展未加载、workspace 不匹配或远程 workspace 时，doctor 给出可操作提示。

## Requirements

- VS Code endpoint 固定为 `127.0.0.1:64345`，不能由 HTML 或用户配置覆盖。
- VS Code 使用独立 token `~/.config/easy-cr/vscode-token`。
- 扩展使用 TypeScript，实现统一的 references/open/health 协议。
- 引用查询调用 `vscode.executeReferenceProvider`，不实现语言分析，不启动 gopls。
- `open` 使用 `workspace.openTextDocument`、`window.showTextDocument`、selection 和 revealRange。
- 扩展只匹配已打开的本地 workspace folder，并校验真实路径、Git fingerprint、base 和 context。
- 对 provider 返回空数组按“无引用”处理；稳定 API 无法可靠区分无 provider 与零引用，不伪造检测结果。
- 首版检测到 Remote SSH、WSL、Dev Container 或 Codespaces 时返回明确的 unsupported 状态。
- 安装器通过 `code --install-extension <vsix> --force` 安装，不直接写 VS Code 应用目录。
- 扩展无运行时第三方依赖或使用 esbuild 打成单文件。
- `status/doctor --json` 不泄露 token。

## Acceptance Criteria

- [ ] `easy-cr init/config editor vscode` 幂等。
- [ ] JavaScript/TypeScript 和安装 Go 扩展后的 Go 文件完成 0/1/N 引用验证。
- [ ] UTF-8 byte column 能正确转换为 VS Code UTF-16 Position。
- [ ] references/open/health 的协议结构与 JetBrains Adapter 一致。
- [ ] workspace 外路径、错误 fingerprint、无效 token、错误 origin 和超大 body 被拒绝。
- [ ] 本地多 root workspace 能精确匹配 `projectPath`。
- [ ] 远程 workspace 返回明确 unsupported，不启动不可访问的 loopback 服务。
- [ ] VSIX 可打包、安装、强制升级和卸载后重装。
- [ ] README、SKILL 和配置参考包含 VS Code 依赖、安装、限制与回退说明。

## Out of Scope

- VS Code Web、github.dev 和 vscode.dev。
- Remote SSH、WSL、Dev Container、Tunnel 和 Codespaces。
- 自动安装 Go、Java、Python 等语言扩展。
- 在 HTML 中动态切换或广播到多个编辑器。
