# Easy CR IntelliJ IDEA Implementation Plan

> 实施时使用 executing-plans 工作流，严格按测试先行推进。

## Task 1：冻结 editor-neutral protocol

- [x] 在 `skills/easy-cr/tests/test_easy_cr.py` 添加新旧 semantic payload、固定 endpoint 和 editor health 的失败测试。
- [x] 在 `skills/easy-cr/references/manifest-schema.md` 记录 protocol v2 请求与响应。
- [x] 运行 `npm test`，确认新增测试先失败。
- [x] 提交：`test: define editor protocol v2`

## Task 2：把 HTML 改为位置驱动

- [x] 为新增行、上下文行、删除行、meta 行和空路径添加点击测试。
- [x] 添加 ASCII、中文、emoji、tab 的 UTF-8 byte column fixture。
- [x] 修改 `skills/easy-cr/assets/review-template.html`，移除 Go-only identifier span 和 HTML symbol 推断。
- [x] 保留旧 `mode=goland` payload 兼容路径。
- [x] 运行 `npm test`。
- [x] 提交：`refactor: make review clicks position based`

## Task 3：建立 editor registry

- [x] 在 `easy_cr_config.py` 为 none、goland、idea 定义不可变 descriptor。
- [x] GoLand 保留端口 64343 和旧 token；IDEA 使用端口 64344 和独立 token。
- [x] 修改 CLI 参数、status、doctor 和 health 校验。
- [x] 添加配置迁移、幂等写入、错误 editor 和 token 不泄露测试。
- [x] 运行 `npm test`。
- [x] 提交：`refactor: add editor registry`

## Task 4：重构通用 JetBrains Adapter

- [x] 将 `assets/goland-plugin` 移动为 `assets/jetbrains-plugin`。
- [x] 为 HTTP、review validation、PSI reference、navigation 拆分组件。
- [x] 写通用 `ReferencesSearch` 的失败测试，再替换 `GoReferencesSearch`。
- [x] 移除 `.go` 限制，保留 project-root 结果过滤。
- [x] 将 PSI 操作放入 read action，将打开和聚焦放入 EDT。
- [x] 在 `plugin.xml` 添加 `com.intellij.modules.lang`。
- [x] 运行 Java self-test 与 `npm test`。
- [x] 提交：`refactor: generalize JetBrains adapter`

## Task 5：Gradle 构建与 IDEA 安装

- [x] 创建 JetBrains Gradle 2.x 构建文件和两个 editor variant 资源。
- [x] 创建 `setup_jetbrains_plugin.py --editor goland|idea`。
- [x] 添加应用检测、插件目录选择、原子安装和不覆盖无关文件测试。
- [x] 保留旧 `setup_goland_plugin.py` 兼容入口并转发到新安装器。
- [x] 构建 GoLand 与 IDEA 插件 ZIP。
- [x] 提交：`feat: install Easy CR into IntelliJ IDEA`

## Task 6：集成验证与文档

- [x] 在 GoLand 验证 Go 文件 0/1/N 引用。
- [x] 在 IntelliJ IDEA 验证 Java 文件 0/1/N 引用。
- [x] 在安装 Go 插件的 IDEA 验证 Go 文件。
- [x] 同时启动 GoLand 和 IDEA，验证端口与 health editor 区分。
- [x] 运行 Plugin Verifier。
- [x] 更新 README、SKILL、configuration reference 和 npm files 清单。
- [x] 运行 `npm test && npm pack --dry-run`。
- [x] 提交：`docs: document IntelliJ IDEA support`

## Completion Gate

- 所有 Acceptance Criteria 通过。
- GoLand 无回归。
- 父任务 design 中的共享协议部分更新为最终实现。
- VS Code 子任务可以只消费 protocol v2，不再修改其基本结构。
