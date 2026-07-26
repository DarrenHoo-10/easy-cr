# Easy CR IntelliJ IDEA 与通用 JetBrains Adapter

## Goal

保留现有 GoLand 行为和旧配置兼容性的同时，让同一套 Easy CR JetBrains 插件源码支持 IntelliJ IDEA，并为后续 VS Code Adapter 提供稳定的编辑器无关协议。

## User Stories

- 用户可以执行 `easy-cr config editor idea` 安装并选择 IntelliJ IDEA。
- 用户在 Easy CR HTML 中 Command+点击任意受支持语言的符号，可以查询 IDEA 已安装语言插件提供的语义引用。
- 用户同时打开 GoLand 和 IDEA 时，HTML 只连接生成时选择的编辑器。
- 旧的 GoLand 配置、端口、token 和已生成 HTML 继续工作。
- 未安装语言能力或无法解析点击位置时，页面显示明确错误，不降级为文本搜索。

## Requirements

- 配置支持 `none|goland|idea`，保留配置 schema version 1。
- GoLand 使用 `127.0.0.1:64343`，IDEA 使用 `127.0.0.1:64344`。
- 新协议以 `filePath + line + UTF-8 byte column` 为输入，不再要求 HTML 解析或发送 symbol。
- HTML 只允许新增行和上下文行触发语义请求；删除行和 meta 行必须拒绝。
- GoLand 与 IDEA 共用 HTTP、CORS、token、body limit、路径边界、Git fingerprint 和打开文件逻辑。
- JetBrains 插件使用平台 PSI/reference 能力，不限制 `.go` 扩展名。
- `plugin.xml` 必须声明 `com.intellij.modules.platform` 和 `com.intellij.modules.lang`。
- IDEA 支持哪些语言取决于用户已安装并启用的 IDEA 语言插件。
- `health` 返回 `editor` 和 `protocolVersion`，CLI 必须校验响应来自所选编辑器。
- 安装器检测 macOS 上的 GoLand 和 IntelliJ IDEA，不关闭或重启 IDE。
- `status/doctor --json` 不输出 token。

## Compatibility

- 保留 GoLand 的旧端口 `64343`。
- 保留 `~/.config/easy-cr/goland-token` 供旧 GoLand HTML 使用。
- IDEA 使用独立的 `~/.config/easy-cr/idea-token`。
- 新 HTML 兼容旧的 `mode=goland` payload，新配置使用 editor-neutral payload。

## Acceptance Criteria

- [ ] `easy-cr init/config editor idea` 可重复执行且结果幂等。
- [ ] GoLand 全部现有测试继续通过。
- [ ] IDEA 对至少 Java 和安装 Go 插件后的 Go 文件完成 0/1/N 引用验证。
- [ ] GoLand 与 IDEA 同时运行时端口不冲突，health 能区分 editor。
- [ ] 中文、emoji、tab 和 ASCII 的 UTF-8/UTF-16 列转换均有测试。
- [ ] 仓库外路径、过期 fingerprint、无效 token、超大 body 和错误 origin 均被拒绝。
- [ ] JetBrains Plugin Verifier 对目标 GoLand 与 IntelliJ IDEA 版本通过。
- [ ] README、SKILL 和配置参考包含 IDEA 安装、依赖、重启与回退说明。

## Out of Scope

- 不安装 IDEA 的 Java、Go 或其他语言插件。
- 不支持在一个 HTML 页面中动态切换编辑器。
- 不实现文本搜索、gopls 或其他语言服务器。
- 本任务不实现 VS Code 扩展。
