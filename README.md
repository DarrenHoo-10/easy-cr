# Easy CR

把 Git Diff 变成一份沿业务流程阅读的交互式 Code Review。

Easy CR 是面向 Codex 和 Claude Code 的本地代码评审插件。它不再让评审者从文件目录猜测业务逻辑，而是按照“请求进入 → 条件判断 → 状态变化 → 返回结果”的顺序组织改动，并生成一份可直接在浏览器中打开的单文件 HTML。

![Easy CR 评审页面](https://raw.githubusercontent.com/DarrenHoo-10/easy-cr/7317ac9674293b4d4d48ceca71b4e9c54dc470f0/docs/images/easy-cr-review.jpg)

## 你可以用它做什么

- 按业务发生顺序阅读代码改动，而不是在文件之间来回跳转。
- 评审当前工作区、最新提交、指定提交或功能分支。
- 搜索、筛选和折叠 Diff，并切换浅色或深色主题。
- 对代码行或选中文字添加评论、回复和汇总。
- 将生成的 HTML 直接发给同事，不依赖在线评审服务。
- 可选连接 GoLand、IntelliJ IDEA 或 VS Code，查询符号引用并跳转到本地代码。

## 环境要求

- Node.js 18+
- Python 3.10+
- Git
- Codex 或 Claude Code

基础评审模式只需要浏览器。编辑器联动目前支持 macOS 本机安装的：

- GoLand
- IntelliJ IDEA
- Visual Studio Code Desktop

## 快速开始

### 1. 安装

```bash
npm install --global easy-cr
```

确认命令可用：

```bash
easy-cr --version
```

### 2. 初始化

```bash
easy-cr init
```

初始化程序会检测本机的 Codex 和 Claude Code，并引导你选择：

- `none`：基础模式，只生成可交互 HTML。
- `goland`：启用 GoLand 引用查询和代码跳转。
- `idea`：启用 IntelliJ IDEA 引用查询和代码跳转。
- `vscode`：启用 VS Code 引用查询和代码跳转。

完成后，根据终端提示重启对应客户端或编辑器。Codex 用户需要新建一个任务，让最新版 Easy CR skill 生效。

也可以使用非交互方式初始化：

```bash
easy-cr init \
  --editor idea \
  --client codex \
  --client claude \
  --non-interactive
```

### 3. 发起一次评审

在目标 Git 仓库中打开 Codex 或 Claude Code，然后直接描述评审范围。

评审当前工作区：

```text
使用 Easy CR 评审当前工作区改动
```

评审最新提交：

```text
使用 Easy CR 评审最新一次提交
```

评审功能分支：

```text
使用 Easy CR 评审 feature/order 相对 main 的改动
```

Easy CR 会分析 Diff、整理业务时序、生成 HTML 并在浏览器中打开。你不需要手工准备评审模板或 manifest。

## 如何使用评审页面

### 阅读改动

- 页面顶部展示改动目标、影响范围和完整业务流程。
- 左侧可以按文件名搜索，并筛选生产代码或测试代码。
- 主区域按照业务阶段从上到下展示说明和对应 Diff。
- 点击“全部折叠”可以快速浏览阶段摘要。

### 添加评论

- 点击行号：评论整行。
- 拖选代码文字：评论选中的内容。
- `Enter`：保存评论。
- `Command+Enter` 或 `Shift+Enter`：在评论中换行。
- 点击顶部“评论 N”：查看、回复、编辑、删除或复制全部评论。

评论保存在当前浏览器中。需要分享时，可以使用“复制评论”整理评审结论。

### 跳转到本地编辑器

配置增强编辑器后，在 Diff 中对可识别的代码标识符执行 `Command+点击`：

- 没有引用：编辑器打开当前代码位置。
- 只有一个引用：直接跳转到调用位置。
- 存在多个引用：页面展示引用列表，选择后跳转。

如果评审生成后代码发生变化，Easy CR 会拒绝使用旧页面跳转。重新生成评审即可继续。

## 编辑器配置

随时切换编辑器：

```bash
easy-cr config editor none
easy-cr config editor goland
easy-cr config editor idea
easy-cr config editor vscode
```

如果该编辑器的 Easy CR 扩展和本机 token 已存在，命令只切换当前配置，不会重复安装扩展，也不会启动或重启编辑器。首次配置或本地文件不完整时，Easy CR 才会安装对应扩展。

需要打开指定项目时，显式执行：

```bash
easy-cr open --project /path/to/repository
```

启动当前配置的编辑器并打开当前项目：

```bash
easy-cr open
```

检查插件安装和运行状态：

```bash
easy-cr doctor
```

如果编辑器尚未启动：

```bash
easy-cr doctor --launch
```

## 常用命令

| 命令 | 用途 |
| --- | --- |
| `easy-cr init` | 初始化客户端与编辑器 |
| `easy-cr status` | 查看当前安装和配置 |
| `easy-cr status --json` | 输出便于诊断的 JSON 状态 |
| `easy-cr config editor <editor>` | 切换基础模式或增强编辑器，不自动启动 |
| `easy-cr open` | 使用当前编辑器打开项目 |
| `easy-cr doctor` | 检查客户端、插件和编辑器联动 |
| `easy-cr doctor --launch` | 启动编辑器后再次检查 |
| `easy-cr --version` | 查看当前版本 |

## 常见问题

### 新建文件没有出现在工作区评审中

Easy CR 默认不包含 Git 未跟踪文件。如果希望新文件进入 Diff，但暂时不提交内容，可以执行：

```bash
git add -N path/to/new-file
```

然后重新生成评审。

### 编辑器联动显示未就绪

先运行：

```bash
easy-cr doctor --launch
```

如果刚安装编辑器插件，请 Reload 或重启编辑器，并确保目标仓库已经在编辑器中打开。

### `easy-cr: command not found`

重新安装并检查 npm 全局可执行目录是否在 `PATH` 中：

```bash
npm install --global easy-cr
npm prefix --global
```

### 评审页提示版本不一致

页面对应的提交或工作区已经发生变化。让 Codex 或 Claude Code 重新生成一次 Easy CR 评审即可。

### 可以同时使用多个编辑器吗

插件可以分别安装到 GoLand、IntelliJ IDEA 和 VS Code，但一份评审页只连接当前配置的编辑器。使用 `easy-cr config editor <editor>` 切换后重新生成评审。

## 从源码安装

克隆仓库后执行：

```bash
python3 scripts/install_cli.py
easy-cr init
```

运行测试：

```bash
npm test
```

## 反馈

如果遇到问题或有功能建议，请在 [GitHub Issues](https://github.com/DarrenHoo-10/easy-cr/issues) 提交反馈。
