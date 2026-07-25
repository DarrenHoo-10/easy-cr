# Easy CR

Easy CR 是一套同时支持 Codex 与 Claude Code 的本地代码评审插件。它将 Git Diff 按业务时序组织成可交互 HTML，支持评论协作，并可选接入 GoLand 的语义引用与代码跳转能力。

## 核心能力

- 按业务触发、判断、状态变化和结果从上到下组织代码改动。
- 每个业务阶段先展示说明，再展示对应 Diff。
- 支持文件筛选、搜索、折叠和黑夜/白天主题。
- 支持选中文字或整行评论，以及评论编辑、删除、回复、汇总和复制。
- `Enter` 保存评论，`Command+Enter` 或 `Shift+Enter` 换行。
- 未配置编辑器时生成完全离线的基础 HTML，不启动额外服务。
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
```

## 通过 npm 安装

包名为 `easy-cr`，安装后会提供同名全局命令：

```bash
npm install --global easy-cr
easy-cr --version
easy-cr init
```

也可以显式指定客户端与基础模式，适合自动化环境：

```bash
easy-cr init --editor none --client codex --client claude --non-interactive
```

npm 仅用于分发，Easy CR 运行时仍需要 Python 3.10+ 和 Git。GoLand 增强模式仅支持 macOS 本机 GoLand。

## 从源码安装

在仓库根目录安装全局命令：

```bash
python3 scripts/install_cli.py
```

首次初始化会检测本机已安装的 Codex 和 Claude Code，并引导选择基础模式或 GoLand 模式：

```bash
easy-cr init
```

常用配置与诊断命令：

```bash
easy-cr status
easy-cr status --json
easy-cr config editor none
easy-cr config editor goland
easy-cr doctor
easy-cr doctor --json
easy-cr --version
```

- `none`：使用基础 HTML，不启用语义引用。
- `goland`：安装受限的 GoLand 扩展，获得代码引用与定位能力；安装后需要手动重启 GoLand。

GoLand 扩展只监听 `127.0.0.1:64343`，使用本机随机 token，并校验项目、Git 评审版本和仓库内文件路径。`doctor` 通过受 token 保护的 `/api/health` 检查扩展是否已经加载，输出中不会包含 token。

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
- Codex 或 Claude 未检测到：显式传入 `--client` 会返回失败；不传时只配置检测到的客户端。
- 全局命令目标已存在：安装器不会覆盖普通文件或无关软链，请先人工确认该文件用途。

## 生成评审 HTML

先按 [manifest-schema.md](skills/easy-cr/references/manifest-schema.md) 准备业务时序 manifest，然后执行：

```bash
python3 skills/easy-cr/scripts/build_review.py \
  --repo /path/to/repository \
  --base HEAD^ \
  --head HEAD \
  --manifest /path/to/review-manifest.json \
  --output /path/to/review.html \
  --context 10
```

生成结果是单文件 HTML，可直接在浏览器打开。评审版本与当前工作区不一致时，GoLand 语义跳转会拒绝执行，避免定位到错误代码。

## 验证

```bash
npm test
npm pack --dry-run
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
- 不启动 `gopls`、Python helper 或其他常驻服务。
- 不在 HTML 中接受前端传入的任意本地 endpoint。
- 不恢复或维护旧的 `easy-cr-pro` 分叉。
