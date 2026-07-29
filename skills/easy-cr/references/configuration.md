# Editor configuration

Easy CR uses one global configuration shared by Codex and Claude Code:

```text
~/.config/easy-cr/config.json
```

Base mode:

```json
{
  "version": 1,
  "editor": "none"
}
```

GoLand mode:

```json
{
  "version": 1,
  "editor": "goland"
}
```

Commands:

```bash
easy-cr init
easy-cr status [--json]
easy-cr config editor none
easy-cr config editor goland
easy-cr doctor [--json]
```

GoLand mode installs a restricted IDE extension and stores a permission-`0600` token at `~/.config/easy-cr/goland-token`. The extension listens only on `127.0.0.1:64343`.

`easy-cr init` also installs the single LaunchAgent-managed comment helper. It listens only on `127.0.0.1:64344` and stores its permission-`0600` token at `~/.config/easy-cr/helper-token`. Report generation checks the helper and starts the same service when needed; multiple reports never create multiple helper processes.

`init` automatically configures installed Codex and Claude Code clients. In automation, use `--non-interactive` together with an explicit `--editor`; repeat `--client` to constrain the clients being configured.

The legacy `configure.py status/set` interface remains available for internal compatibility.
