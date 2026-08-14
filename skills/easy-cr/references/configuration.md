# Editor configuration

Easy CR uses one global configuration shared by Codex, Claude Code, and DeepSeek Harness:

```text
macOS/Linux: ~/.config/easy-cr/config.json
Windows:     %APPDATA%\easy-cr\config.json
```

Base mode:

```json
{
  "version": 1,
  "editor": "none"
}
```

Enhanced editors keep schema version 1 and only change the `editor` field:

```json
{
  "version": 1,
  "editor": "goland"
}
```

```json
{
  "version": 1,
  "editor": "idea"
}
```

```json
{
  "version": 1,
  "editor": "vscode"
}
```

Commands:

```bash
easy-cr init
easy-cr status [--json]
easy-cr config editor none
easy-cr config editor goland
easy-cr config editor idea
easy-cr config editor vscode
easy-cr doctor [--json]
```

## Built-in editor registry

| editor | display name | endpoint | token filename |
| --- | --- | --- | --- |
| `none` | 基础模式 | — | — |
| `goland` | GoLand | `http://127.0.0.1:64343` | `goland-token` |
| `idea` | IntelliJ IDEA | `http://127.0.0.1:64344` | `idea-token` |
| `vscode` | Visual Studio Code | `http://127.0.0.1:64345` | `vscode-token` |

Token files live beside `config.json` in the platform-specific configuration directory.

Endpoints and ports come only from this built-in registry. HTML never accepts a caller-supplied local endpoint.

The single Easy CR comment helper listens on
`http://127.0.0.1:64346`. This port is reserved separately from the three
editor endpoints so IntelliJ IDEA and the helper can run at the same time.

## Protocol v2 semantic payload

When an enhanced editor is configured and its token is present, generated HTML embeds:

```json
{
  "mode": "editor",
  "editor": "idea",
  "displayName": "IntelliJ IDEA",
  "endpoint": "http://127.0.0.1:64344",
  "protocolVersion": "2",
  "token": "..."
}
```

Legacy pages with `mode: "goland"` remain readable. New generators always emit `mode: "editor"`.

## Position request

HTML sends repository-relative path, 1-based line, and 1-based UTF-8 byte column:

```json
{
  "token": "...",
  "projectPath": "/repo",
  "reviewType": "worktree",
  "fingerprint": "...",
  "base": "HEAD^",
  "context": 10,
  "filePath": "src/service.go",
  "line": 42,
  "column": 18
}
```

`/api/health` returns:

```json
{
  "ready": true,
  "plugin": "easy-cr",
  "editor": "idea",
  "protocolVersion": 2
}
```

CLI health checks require matching `editor` and `protocolVersion`.

## Installation notes

- `easy-cr config editor <editor>` only changes the active editor when that editor's adapter and token already exist.
- When the adapter or token is missing, `easy-cr config editor goland|idea` installs the JetBrains adapter via `setup_jetbrains_plugin.py`.
- When the adapter or token is missing, `easy-cr config editor vscode` builds a VSIX via `setup_vscode_extension.py` and installs it with the discovered VS Code CLI (`code --install-extension --force`).
- `easy-cr config editor <editor>` and `easy-cr init` never launch or restart an editor. Use `easy-cr open` or `easy-cr doctor --launch` when launching is desired.
- VS Code CLI discovery order: `PATH` 中的 `code` → Windows 用户/系统安装目录 → macOS `Visual Studio Code.app` 内置 CLI → 常见绝对路径。
- Windows JetBrains discovery covers `PATH`, JetBrains Toolbox, `Program Files`, and `%LOCALAPPDATA%\Programs\JetBrains`. Plugins install under `%APPDATA%\JetBrains\<product-version>\plugins`.
- 在 macOS/Linux 上，若 `PATH` 中没有 `code`，安装器会尽量在 `~/.local/bin/code` 创建指向应用内 CLI 的软链（不覆盖已有文件）。Windows 直接复用发现到的 `code.cmd` 或 `Code.exe`，不创建软链。
- The legacy `setup_goland_plugin.py` entrypoint forwards to `--editor goland`.
- POSIX token files use permission `0600`; Windows token files inherit the current user's ACL in `%APPDATA%\easy-cr`.
- `easy-cr init` registers the comment helper as a macOS LaunchAgent or a Windows user Startup command and starts it immediately.
- VS Code adapter supports local Desktop workspaces only; Remote SSH/WSL/Dev Containers/Codespaces are unsupported in v1.
- Enhanced editors must run inside the target IDE process. If the IDE is not running:
  - CLI: `easy-cr open` / `easy-cr doctor --launch` uses `open -a` on macOS and the discovered native executable on Windows.
  - HTML: Command+click (macOS) or Ctrl+click (Windows) connection failures open `launchUri` (for example `vscode://file...`) and retry health/API for a short window while the extension loads.
- Launching the app is best-effort. Semantic references still require the Easy CR extension to finish loading in an opened local workspace.
- `init` automatically configures installed Codex, Claude Code, and DeepSeek Harness clients. `--client dsh` installs the persistent `dsh-easy-cr` bundle into the `web` profile (`dsh plugin --profile web add ./packages/dsh-easy-cr`); it does not copy a skill into `~/.dsh/skills`. Restart `dsh web` after install. In automation, use `--non-interactive` together with an explicit `--editor`; repeat `--client` to constrain the clients being configured.
- The legacy `configure.py status/set` interface remains available for internal compatibility.
