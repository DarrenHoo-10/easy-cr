# Easy CR 支持 IntelliJ IDEA 与 VS Code

## Goal

在保留 Easy CR 单文件 HTML、评论能力和基础模式回退的前提下，将现有 GoLand 语义引用与代码定位能力扩展到 IntelliJ IDEA 和 Visual Studio Code。

## Confirmed Facts

- 当前配置协议仅支持 `none|goland`，GoLand endpoint 固定为 `127.0.0.1:64343`。
- HTML 已有稳定的 `/api/references`、`/api/open`、`/api/health` 协议，不需要为新编辑器复制模板交互。
- GoLand 扩展当前直接使用 `GoReferencesSearch`，并校验项目根目录、Git review fingerprint、仓库内 Go 文件、行列和 token。
- IntelliJ IDEA 和 GoLand 都基于 IntelliJ Platform，可以共用位置解析、引用搜索和代码打开逻辑。
- VS Code 可以通过 `vscode.executeReferenceProvider` 使用当前文件已注册的语言引用提供器，通过 `showTextDocument` 打开并定位代码。
- 当前 CLI、status、doctor 和安装脚本均写死 GoLand，需要先抽象 editor descriptor、endpoint、安装器和诊断器。

## Requirements

- CLI 支持 `none|goland|idea|vscode`，初始化、切换、状态和诊断保持幂等。
- 一个评审 HTML 只绑定生成时配置的一个编辑器，不允许页面动态传入任意 endpoint。
- 三种增强编辑器复用同一份 HTML 协议、鉴权规则、Git 版本校验和引用返回结构。
- Easy CR 不识别编程语言、不维护关键字表，也不由 HTML 推断 symbol；Command+点击只计算仓库文件、行和 UTF-8 列，具体符号与引用由所选编辑器解析。
- GoLand 现有配置与已生成 HTML 保持兼容；新增配置不能迫使老用户立即迁移。
- IntelliJ IDEA 使用其 PSI/reference provider；支持哪些语言取决于 IDEA 已安装并启用的语言插件。
- VS Code 使用扩展宿主和当前语言已注册的 reference provider；支持哪些语言取决于 VS Code 已安装并启用的语言扩展。
- Easy CR 不额外启动 helper、语言服务器或 `gopls`。
- 不同编辑器必须避免本地端口冲突，`doctor` 能区分应用缺失、扩展缺失、依赖缺失、未加载和 token/版本错误。
- 安装过程不自动关闭或重启编辑器，只给出明确提示。
- 基础模式继续生成完全离线 HTML，不嵌入 endpoint 或 token。

## Acceptance Criteria

- [ ] `easy-cr init/config editor` 可选择 GoLand、IntelliJ IDEA、VS Code 或基础模式。
- [ ] IntelliJ IDEA 使用当前文件对应的 PSI/reference provider 查询引用，并按 0/1/N 引用规则定位或展示列表。
- [ ] VS Code 使用当前文件对应的 reference provider 查询引用，并按相同规则定位或展示列表。
- [ ] 三种编辑器返回相同的引用协议，HTML 模板无需按编辑器分叉。
- [ ] HTML 不再仅为 `.go` 文件预生成标识符 span；Command+点击任意新增行或上下文行时按光标位置发起查询。
- [ ] 同时打开多个编辑器时不会因监听端口冲突导致错误编辑器响应。
- [ ] 所有增强模式都拒绝仓库外路径、过期 review fingerprint 和无效 token。
- [ ] GoLand 旧配置和旧 token 在升级后继续可用。
- [ ] `easy-cr status/doctor --json` 展示所选编辑器的安装、依赖和运行时状态，不泄露 token。
- [ ] 每个编辑器适配器都有协议、鉴权、版本校验、0/1/N 引用和代码定位测试。
- [ ] README 明确各编辑器的依赖、安装方式、重启要求和回退行为。

## Out of Scope

- 不支持浏览器在多个编辑器间临时切换或广播打开。
- 不由 Easy CR 安装 SDK、GoLand、IntelliJ IDEA、VS Code、语言插件或语言服务器。
- 不新增云端服务、MCP、本地 Python helper 或常驻 `gopls`。
- 首期不承诺远程开发、Dev Container、WSL、SSH workspace。
