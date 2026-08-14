# dsh-easy-cr

Easy CR 的 DeepSeek Harness **常驻插件**。装进 `web` profile 后，每次 `dsh web` 都会挂上：

- 内嵌 `easy-cr` skill（正文来自仓库 `skills/easy-cr/SKILL.md`）
- `/easy-cr` 本身是 skill 调用，不要子命令；自然语言描述范围即可生成报告

这不是把 skill 拷到 `~/.dsh/skills`。卸载插件后 skill 和命令一起消失。

## 安装

在 Easy CR 仓库根目录：

```bash
dsh plugin --profile web add ./packages/dsh-easy-cr
```

或使用 CLI：

```bash
easy-cr init --client dsh --editor none --non-interactive
```

确认层已进入组合：

```bash
dsh --profile web --dump-config
```

输出里应有 `# == dsh-easy-cr`。然后重启当前 `dsh web`。

卸载：

```bash
dsh plugin --profile web remove dsh-easy-cr
```

## 使用

在 DeepSeek Harness 会话里，下面几种写法都会加载内置 skill，不需要 `/easy-cr status` 这类子命令：

- `/easy-cr`
- `/easy-cr 评审当前工作区改动`
- `用 Easy CR 评审最新一次提交`
- `评审 feature/order 相对 main 的改动`

模型应先加载 skill `easy-cr`，再按 skill 正文生成 HTML。生成报告仍需要本机 `easy-cr` CLI（`npm install --global easy-cr`）。查看安装状态请用终端里的 `easy-cr status` / `easy-cr doctor`。

生成报告前必须读到当前 Web 的 `$DSH_SESSION_ID` 和 `$DSH_WEB_URL`（例如跑在 8080 就是 `http://127.0.0.1:8080`），并写进报告绑定。发送评论或提问只使用这些已准备的地址，以及可选的 `$EASY_CR_DSH_ENDPOINT`。不扫描端口。Host 换了地址就用当前 `$DSH_WEB_URL` 重生报告，或手动设置 `EASY_CR_DSH_ENDPOINT`。绑定成功后：

- **发送评论给 AI** 把批次打回原 DSH 会话（`session.prompt`）
- **不懂就问** 在本机 Host 上开只读解释会话，不改原会话

需要 `dsh web` 在跑。相对脚本路径相对 skill 目录 `skills/easy-cr` 解析。

## 尚未包含

helper 收进插件进程生命周期、Web 设置页 / Chat 卡片，属于后续阶段。
