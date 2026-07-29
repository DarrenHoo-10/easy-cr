# Easy CR

Easy CR 是一套同时支持 Codex 与 Claude Code 的本地代码评审插件。它将 Git Diff 按业务时序组织成可交互 HTML，支持评论协作，并可选接入 GoLand 的语义引用与代码跳转能力。

## 核心能力

- 按技术方案章节组织首页，再按业务触发、判断、状态变化和结果逐步讲解代码。
- 同一章节可连续展示多个仓库的代码，不需要在多份报告之间切换。
- 每一步的目标、判断、结果和代码注释在生成报告时写入，浏览器不会临时调用 AI。
- 支持章节概览、讲解模式和完整 Diff 三种阅读方式。
- 支持文件筛选、搜索、折叠和黑夜/白天主题。
- 支持全文、章节、选中文字和整行评论，以及评论编辑、删除、回复、解决、汇总和复制。
- 评论通过单实例本地服务直接写回当前 HTML；服务暂时不可用时保留待写入草稿，恢复后继续写回原文件。
- AI 可通过 `easy-cr comments <html> --json` 直接读取 HTML 内的人工评论。
- 评论状态为“未处理 → 处理中 → 已解决”。右上角“发送评论给 AI”只发送未处理评论，并通知生成报告的原 Codex/Claude 任务开始处理。
- 重新生成同一报告时保留历史评论；本轮反馈修改使用深绿色，已评审新增代码使用浅绿色，删除代码使用浅红色。
- 章节讲解必须覆盖除测试、依赖和纯 import 之外的全部生产代码 Diff；遗漏时生成器直接报错。
- `Enter` 保存评论，`Command+Enter` 或 `Shift+Enter` 换行。
- 未配置编辑器时不启用语义引用；评论写回仍复用 Easy CR 本地服务。
- 配置 GoLand 后，使用 `Command+点击` 查询 Go 标识符的语义引用：
  - 无引用：GoLand 定位当前代码。
  - 一个引用：GoLand 直接定位唯一调用位置。
  - 多个引用：HTML 展示引用列表，选择后再跳转 GoLand。

## 目录结构

```text
easy-cr/
├── bin/easy-cr
├── scripts/install_cli.py
├── .codex-plugin/plugin.json
├── .claude-plugin/
│   ├── plugin.json
│   └── marketplace.json
├── skills/easy-cr/
│   ├── SKILL.md
│   ├── agents/openai.yaml
│   ├── assets/
│   │   ├── review-template.html
│   │   └── goland-plugin/
│   ├── references/
│   ├── scripts/
│   └── tests/
└── README.md
```

## 环境要求

- Python 3.10+
- Git
- Codex 或 Claude Code
- GoLand 增强模式仅支持 macOS 本机 GoLand

## 编辑器配置

Codex 与 Claude Code 共用用户级配置：

```text
~/.config/easy-cr/config.json
~/.config/easy-cr/goland-token
~/.config/easy-cr/helper-token
```

安装全局命令：

```bash
python3 scripts/install_cli.py
```

首次初始化会检测本机已安装的 Codex 和 Claude Code，并引导选择基础模式或 GoLand 模式：

```bash
easy-cr init
```

自动化环境可显式指定配置：

```bash
easy-cr init --editor none --client codex --client claude --non-interactive
```

常用配置与诊断命令：

```bash
easy-cr status
easy-cr status --json
easy-cr config editor none
easy-cr config editor goland
easy-cr doctor
easy-cr doctor --json
easy-cr comments /path/to/review.html
easy-cr comments /path/to/review.html --json
easy-cr comments /path/to/review.html --resolve-batch <batch-id>
easy-cr --version
```

- `none`：使用基础 HTML，不启用语义引用。
- `goland`：安装受限的 GoLand 扩展，获得代码引用与定位能力；安装后需要手动重启 GoLand。

GoLand 扩展只监听 `127.0.0.1:64343`，使用本机随机 token，并校验项目、Git 评审版本和仓库内文件路径。`doctor` 通过受 token 保护的 `/api/health` 检查扩展是否已经加载，输出中不会包含 token。

评论服务由 macOS LaunchAgent `com.bytedance.easy-cr.helper` 管理，只监听 `127.0.0.1:64344`。`easy-cr init` 会安装并启动它；生成报告时也会检查服务状态，未运行时只拉起同一个实例。所有报告共用该服务，不会按报告创建进程。

## 安装

### Codex

推荐统一初始化：

```bash
easy-cr init --editor none --client codex --non-interactive
```

该命令会原子更新 `~/.agents/plugins/marketplace.json` 中的 Easy CR 条目，并保留其他插件配置。
更新后请新建 Codex 任务加载最新版 skill。

### Claude Code

```bash
easy-cr init --editor none --client claude --non-interactive
```

更新后重启 Claude Code。

## 常见问题

- `easy-cr: command not found`：确认 `~/.local/bin` 在 `PATH`，再执行 `python3 scripts/install_cli.py`。
- `doctor` 提示 GoLand runtime 未就绪：先确认 GoLand 已打开目标项目；刚安装扩展时需要手动重启 GoLand。
- `doctor` 提示 helper 未就绪：重新执行 `easy-cr init --editor none --non-interactive`；生成报告时也会自动尝试拉起。
- Codex 或 Claude 未检测到：显式传入 `--client` 会返回失败；不传时只配置检测到的客户端。
- 全局命令目标已存在：安装器不会覆盖普通文件或无关软链，请先人工确认该文件用途。

## 生成评审 HTML

先按 [manifest-schema.md](skills/easy-cr/references/manifest-schema.md) 准备 schema v2 manifest。仓库、revision、章节和代码范围都写在 manifest 中：

```bash
python3 skills/easy-cr/scripts/build_review.py \
  --manifest /path/to/review-manifest.json \
  --output /path/to/repo/.codex-artifacts/review.html \
  --context 10
```

v1 单仓库 manifest 仍兼容原有 `--repo --base --head` 参数。报告应生成到任一受评仓库的 `.codex-artifacts` 目录；评论服务只允许修改生成阶段注册的该文件。评审版本与当前工作区不一致时，GoLand 语义跳转会拒绝执行，避免定位到错误代码。

Agent 收到评论批次后先读取对应 `aiBatchId` 的处理中评论。如果批次内存在询问、讨论、无需改代码、需要确认或 Agent 有异议的内容，会先一次性向用户确认，整批不立即改动。实现、验证并重新生成报告后，再用 `--resolve-batch` 将该批次置为已解决。

评论状态、批次发送、报告重生成和错误处理的完整契约见 [review-lifecycle.md](skills/easy-cr/references/review-lifecycle.md)。

## 验证

```bash
python3 -m py_compile skills/easy-cr/scripts/*.py
python3 -m unittest discover -s skills/easy-cr/tests -v
python3 skills/easy-cr/scripts/setup_goland_plugin.py \
  --build-only /tmp/easy-cr.jar
```

插件结构校验：

```bash
python3 ~/.codex/skills/.system/plugin-creator/scripts/validate_plugin.py .
python3 ~/.codex/skills/.system/skill-creator/scripts/quick_validate.py skills/easy-cr
claude plugin validate . --strict
```

## 开发约束

- 基础模式和 GoLand 增强模式必须共用同一份模板与生成器。
- 不使用文本搜索模拟语义引用。
- 不启动 `gopls`；评论只使用一个由 LaunchAgent 管理的 Easy CR helper。
- 不在浏览器运行时请求 AI 生成讲解。
- 不在 HTML 中接受前端传入的任意本地 endpoint。
- 不恢复或维护旧的 `easy-cr-pro` 分叉。
