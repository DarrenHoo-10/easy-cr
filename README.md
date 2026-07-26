# Easy CR

**AI 写代码，人工只做一次高质量 CR。**

Codex、Claude Code 让代码生成越来越快，但生产级代码依然必须经过人工评审。Easy CR 把 AI 生成的分散改动整理成一份沿技术方案展开的交互式 Diff，让你一次看清、一次评论，再让 AI 直接根据 HTML 中的评论精准修改。

![Easy CR：评论后由 AI 直接修改，并跳转编辑器深度评审](https://raw.githubusercontent.com/DarrenHoo-10/easy-cr/d0dc92a8edbaaed6edf2f0122fb545287803687e/docs/demo/easy-cr-workflow.gif)

[查看 12 秒完整演示视频](https://raw.githubusercontent.com/DarrenHoo-10/easy-cr/d0dc92a8edbaaed6edf2f0122fb545287803687e/docs/demo/easy-cr-workflow.mp4)

## Easy CR 解决什么问题

### AI 改了很多文件，不知道从哪里开始看

一次需求可能同时修改入口、业务逻辑、数据结构和测试。代码散落在不同文件中，直接看 Git Diff 很难快速还原完整方案。

Easy CR 会让 AI 先理解技术方案和执行链路，再按照“请求进入 → 核心判断 → 状态变化 → 结果验证”的顺序组织代码 Diff。你看到的是一条可以顺着读完的评审路径，而不是一堆等待自己拼接的文件。

### 多个问题要反复告诉 AI，CR 被切成很多轮

传统流程里，发现一个问题就和 AI 交互一次；后面又发现新问题，还要继续补充上下文、等待修改、重新检查。问题越多，往返次数越多。

Easy CR 允许你在报告中对具体代码行或选中的代码直接评论。把需要调整的地方一次标完后，只需告诉 AI：

```text
根据 Easy CR HTML 中的所有评论修改代码
```

AI 会读取评论对应的文件、行号和代码上下文，一次处理全部评审意见。**这是 Easy CR 的核心工作流：人完成一次 CR，AI 完成一次集中修改。**

## 一次完整的 CR

1. Codex 或 Claude Code 完成需求开发。
2. 让 Easy CR 按技术方案生成交互式 HTML Diff。
3. 人工沿业务流程评审，在所有需要修改的位置添加评论。
4. 让 AI 直接读取 HTML 评论并一次完成修改。

遇到需要深挖的逻辑时，按住 `Command` 点击代码标识符即可查看项目内引用：

- 没有引用时，打开当前代码位置。
- 只有一处引用时，直接跳到调用位置。
- 有多处引用时，在 HTML 中列出所有调用位置，选择后跳转。

目前支持跳转到 GoLand、IntelliJ IDEA 和 Visual Studio Code。你可以留在 Easy CR 中把握整体方案，也可以随时进入熟悉的编辑器做深度评审。

## 快速开始

### 1. 安装

```bash
npm install --global easy-cr
```

确认安装成功：

```bash
easy-cr --version
```

### 2. 初始化

```bash
easy-cr init
```

初始化时可以选择：

- `none`：只使用交互式 HTML 评审。
- `goland`：启用 GoLand 方法引用与代码跳转。
- `idea`：启用 IntelliJ IDEA 方法引用与代码跳转。
- `vscode`：启用 VS Code 方法引用与代码跳转。

也可以直接完成非交互配置：

```bash
easy-cr init \
  --editor vscode \
  --client codex \
  --client claude \
  --non-interactive
```

Codex 用户初始化后新建一个任务，让 Easy CR skill 生效。

### 3. 生成评审

在目标 Git 仓库中打开 Codex 或 Claude Code，直接描述评审范围。

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

Easy CR 会分析改动、还原技术方案、生成 HTML 并在浏览器中打开。

### 4. 评论后让 AI 修改

在评审页面中：

- 点击行号，评论整行。
- 拖选代码，评论选中的内容。
- 按 `Enter` 保存评论。
- 按 `Command+Enter` 或 `Shift+Enter` 在评论中换行。
- 点击顶部“评论 N”检查全部评审意见。

确认评论完成后，回到当前 Codex 或 Claude Code 会话：

```text
根据 Easy CR HTML 中的所有评论修改代码，完成后告诉我每条评论是如何处理的
```

不需要逐条复制评论，也不需要为每个问题单独和 AI 交互。

## 编辑器联动

随时切换评审使用的编辑器：

```bash
easy-cr config editor none
easy-cr config editor goland
easy-cr config editor idea
easy-cr config editor vscode
```

如果目标编辑器已经配置过，命令只切换当前选择，不会重复安装扩展，也不会启动或重启编辑器。只有首次配置或本地配置不完整时，Easy CR 才会补齐安装。

需要打开项目时显式执行：

```bash
easy-cr open --project /path/to/repository
```

检查插件和编辑器联动状态：

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
| `easy-cr init` | 初始化 Codex、Claude Code 和编辑器 |
| `easy-cr status` | 查看当前安装与配置 |
| `easy-cr config editor <editor>` | 切换评审编辑器，不自动启动 |
| `easy-cr open` | 使用当前编辑器打开项目 |
| `easy-cr doctor` | 检查插件和编辑器联动 |
| `easy-cr doctor --launch` | 启动编辑器后再次检查 |
| `easy-cr --version` | 查看版本 |

## 常见问题

### 新文件没有出现在评审中

Easy CR 默认不包含 Git 未跟踪文件。如果希望新文件进入工作区 Diff，但暂时不提交内容：

```bash
git add -N path/to/new-file
```

然后重新生成评审。

### 编辑器联动显示未就绪

先确保目标仓库已经在编辑器中打开，再执行：

```bash
easy-cr doctor
```

如果扩展刚安装，请 Reload 编辑器窗口后重试。

### 评审页提示版本不一致

评审生成后代码已经发生变化。让 Codex 或 Claude Code 重新生成 Easy CR 评审，确保评论和跳转始终对应当前代码。

### 可以同时安装多个编辑器插件吗

可以。插件可以分别安装到 GoLand、IntelliJ IDEA 和 VS Code，但一份评审只连接当前配置的编辑器。切换后重新生成评审即可。

## 从源码运行

```bash
python3 scripts/install_cli.py
easy-cr init
npm test
```

## 反馈

欢迎通过 [GitHub Issues](https://github.com/DarrenHoo-10/easy-cr/issues) 提交问题和建议。
