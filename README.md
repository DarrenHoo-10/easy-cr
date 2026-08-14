# Easy CR

**按技术方案看懂 AI 改动，集中完成 CR，一次把所有评论发回 AI。**

Codex、Claude Code 和 DeepSeek Harness 让代码生成越来越快，但生产级代码仍然需要人工把关。
Easy CR 把散落在多个文件、甚至多个仓库中的改动，整理成一份沿技术方案和
业务执行顺序展开的交互式报告。你可以在同一份报告里完成多轮评论，然后点击
一次按钮，把本轮所有意见直接发送给原来的 AI 会话。

![Easy CR：评论后由 AI 直接修改，并跳转编辑器深度评审](https://raw.githubusercontent.com/DarrenHoo-10/easy-cr/d0dc92a8edbaaed6edf2f0122fb545287803687e/docs/demo/easy-cr-workflow.gif)

[查看 12 秒完整演示视频](https://raw.githubusercontent.com/DarrenHoo-10/easy-cr/d0dc92a8edbaaed6edf2f0122fb545287803687e/docs/demo/easy-cr-workflow.mp4)

## 三个核心能力

### 1. 按技术方案组织 CR 报告

普通 Diff 按文件排列代码，评审者需要自己还原“为什么改、先看哪里、各文件如何
协作”。Easy CR 会先理解技术方案，再把改动组织成：

- 技术方案章节；
- 按业务执行顺序排列的步骤；
- 大步骤中按业务逻辑闭环组织的可导航评审小节；
- 每一步的目标、关键决策、结果和代码解释；
- 与步骤直接相关的最小完整代码范围；
- 可随时切换的完整 Diff。

一次需求即使横跨多个文件或多个仓库，也会被放进同一条可顺着读完的评审路径，
而不是拆成互不关联的文件列表。

当一个步骤包含较多代码时，Easy CR 不按固定行数机械切割，而是先识别完整的业务
判断、状态变化和外部调用，再在不切断事务、错误处理和控制流的边界上形成小节。
200～300 行仅用于提示模型重新检查评审负担；如果逻辑高度内聚可以继续保持完整，
如果存在多个独立业务闭环，即使代码更少也会拆分。页面会显示每个小节的 Diff
负担和拆分依据，便于评审者判断上下文是否完整。

### 2. 多次评论，只和 AI 交互一次

评审时不需要发现一个问题就打断 AI 一次。你可以在报告中持续添加：

- 整份报告评论；
- 技术方案章节评论；
- 代码行评论；
- 跨行选区评论；
- 评论回复。

所有意见都保留在当前 HTML 中，并按照
`未处理 → 处理中 → 已解决` 跟踪状态。你可以先把一轮 CR 完整做完，再让 AI
一次读取和处理本轮全部评论。报告重新生成后，历史评论、回复和处理状态仍会保留，
方便继续下一轮评审。

### 3. 直接发送评论给 AI

不需要复制评论，不需要回到聊天窗口重新描述问题。完成一轮评审后，点击报告右上角
的 **发送评论给 AI**：

1. Easy CR 只发送本轮尚未处理的评论；
2. 评论立即进入“处理中”状态；
3. 原来的 Codex、Claude Code 或后续接入的 DeepSeek Harness 会话自动恢复；
4. AI 读取评论对应的文件、代码范围和上下文；
5. 修改、验证并重新生成同一份报告；
6. AI 回复每条评论的处理结果，并将本批评论标记为“已解决”。

每次发送都有独立批次，不会重复发送正在处理或已经解决的评论。

## 一次完整的 CR 闭环

1. Codex、Claude Code 或 DeepSeek Harness 完成需求开发。
2. Easy CR 按技术方案和业务顺序生成交互式 CR 报告。
3. 人工沿章节和步骤阅读代码，在报告中完成本轮所有评论。
4. 点击 **发送评论给 AI**，一次提交本轮全部未处理意见。
5. AI 在原会话中集中处理评论、运行验证并重新生成同一路径报告。
6. 人工查看本轮修改和评论状态，必要时继续下一轮 CR。

重新生成后，上一轮已经看过的新增代码显示为浅绿色，本轮反馈产生的修改显示为
深绿色，删除显示为浅红色，方便快速聚焦最新变化。

遇到需要深挖的逻辑时，macOS 按住 `Command`、Windows 按住 `Ctrl` 点击代码标识符即可查看项目内引用：

- 没有引用时，打开当前代码位置。
- 只有一处引用时，直接跳到调用位置。
- 有多处引用时，在 HTML 中列出所有调用位置，选择后跳转。

目前支持跳转到 GoLand、IntelliJ IDEA 和 Visual Studio Code。你可以留在 Easy CR 中把握整体方案，也可以随时进入熟悉的编辑器做深度评审。

## 快速开始

Easy CR 支持 macOS 和 Windows 10/11，需要 Node.js 18+、Python 3.10+ 与 Git。
Windows 同时支持 `py -3` 和 `python`，不要求系统存在 `python3` 命令。

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
  --client dsh \
  --non-interactive
```

PowerShell 可直接写成一行：

```powershell
easy-cr init --editor vscode --client codex --client claude --client dsh --non-interactive
```

DeepSeek Harness 会把 `packages/dsh-easy-cr` 装进 `web` profile，作为常驻插件，而不是拷一份 skill 到 `~/.dsh/skills`：

```bash
dsh plugin --profile web add ./packages/dsh-easy-cr
```

装好后重启 `dsh web`。可用 `dsh --profile web --dump-config` 确认出现 `# == dsh-easy-cr`。Codex 用户初始化后新建一个任务，让 Easy CR skill 生效。

### 3. 生成评审

在目标 Git 仓库中打开 Codex、Claude Code 或 DeepSeek Harness，直接描述评审范围。DeepSeek Harness 里也可以只输入 `/easy-cr`，或 `/easy-cr` 后面跟自然语言，不必带子命令。

评审当前工作区：

```text
使用 Easy CR 评审当前工作区改动
```

```text
/easy-cr 评审当前工作区改动
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
每次 CR 默认保存在目标仓库的
`.codex-artifacts/YYYY-MM-DD-技术方案名称/` 目录中。目录名称取当前报告
`subject`，不同方案会进入不同目录；其中 `manifest.json` 记录报告结构，
`review.html` 用于评审。同一轮评论后的重新生成会继续复用这个目录。

### 4. 评论、添加到任务并发送给 AI

在评审页面中：

- 在报告、章节、代码行或选中代码上添加评论；代码选区右键仍显示 **评论 / 不懂就问**。
- 选中「不懂就问」对话中的文本后，右键只显示 **添加到任务**；页面会在选区旁展示轻量输入框。Enter 保存并收起输入框，Command/Ctrl+Enter 和 Shift+Enter 用于换行，Escape 取消，不会在保存时发送。
- 已保存注释以 Codex 风格的蓝色评论气泡编号标在原文右上角，点击编号可以再次编辑；新增下一条时，已有编号继续保留。注释汇总为当前问答输入区的 **N 条注释**，悬浮可查看所选文本和用户评论。
- 点击现有「不懂就问」发送按钮时，注释才会随问题一起提交。发送区仅显示注释数量和问题正文，不展开注释详情；页面上的编号和汇总会立即清除。请求失败时保留这条紧凑消息，并提供重新发送入口。
- 对话注释只保存在当前页面的任务草稿中，不计入评论数量，也不参与评论状态流转；刷新页面会保留，显式发送开始或重新生成报告后清空。
- 代码选区右键选择 **不懂就问**，可在代码下方先提问并继续追问。同一技术方案共用一个只读解释会话并按提问顺序处理，页面仍按代码位置分别展示问答。
- 对已有评论继续回复。
- 按 `Enter` 保存评论。
- 按 `Command/Ctrl+Enter` 或 `Shift+Enter` 在评论中换行。
- 点击顶部“评论 N”检查本轮全部评审意见。
- 点击右上角 **发送评论给 AI**。

Easy CR 会恢复生成这份报告的原始 Codex、Claude Code 或 DeepSeek Harness 会话，并将本轮未处理
评论作为一个批次交给 AI。你无需复制评论，也无需为每个问题单独发起一次交互。
DeepSeek Harness 绑定在生成报告前准备：记下当时的 `$DSH_SESSION_ID` 和 `$DSH_WEB_URL`。回投只打这个已记录的本机 Web 地址，不扫描端口。

## 编辑器联动

随时切换评审使用的编辑器：

```bash
easy-cr config editor none
easy-cr config editor goland
easy-cr config editor idea
easy-cr config editor vscode
```

如果目标编辑器已经配置过，命令只切换当前选择，不会重复安装扩展，也不会启动或重启编辑器。只有首次配置或本地配置不完整时，Easy CR 才会补齐安装。

Windows 会自动发现 PATH、Visual Studio Code 的用户/系统安装目录，以及 JetBrains
Toolbox、`Program Files` 和用户级 `Programs` 中的 GoLand/IntelliJ IDEA。配置和 token
位于 `%APPDATA%\easy-cr`；macOS 仍使用 `~/.config/easy-cr`。`easy-cr init` 还会在
Windows 用户启动目录注册评论服务，并立即以后台进程启动。

需要打开项目时显式执行：

```bash
easy-cr open --project /path/to/repository
```

PowerShell 示例：

```powershell
easy-cr open --project C:\work\repository
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
| `easy-cr init` | 初始化 Codex、Claude Code、DeepSeek Harness 和编辑器 |
| `easy-cr status` | 查看当前安装与配置 |
| `easy-cr config editor <editor>` | 切换评审编辑器，不自动启动 |
| `easy-cr open` | 使用当前编辑器打开项目 |
| `easy-cr doctor` | 检查插件和编辑器联动 |
| `easy-cr doctor --launch` | 启动编辑器后再次检查 |
| `easy-cr comments <report> --json` | 查看报告中的评论与处理状态 |
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

评审生成后代码已经发生变化。让 Codex、Claude Code 或 DeepSeek Harness 重新生成 Easy CR 评审，确保评论和跳转始终对应当前代码。

### “发送评论给 AI”不可用

先检查单实例评论服务和客户端安装状态：

```bash
easy-cr doctor
```

评论服务固定监听本机 `127.0.0.1:64346`，只处理已注册的 Easy CR 报告。修复
诊断项后，重新生成同一路径报告即可恢复评论持久化和发送能力。

### 可以同时安装多个编辑器插件吗

可以。插件可以分别安装到 GoLand、IntelliJ IDEA 和 VS Code，但一份评审只连接当前配置的编辑器。切换后重新生成评审即可。

## 从源码运行

macOS/Linux：

```bash
python3 scripts/install_cli.py
easy-cr init
npm test
```

Windows PowerShell：

```powershell
python scripts/install_cli.py
$env:PATH += ";$HOME\.local\bin"
easy-cr init
npm test
```

通过 `npm install --global easy-cr` 安装时，npm 会直接创建 Windows 命令入口，不需要手动修改 PATH。

## 反馈

欢迎通过 [GitHub Issues](https://github.com/DarrenHoo-10/easy-cr/issues) 提交问题和建议。
