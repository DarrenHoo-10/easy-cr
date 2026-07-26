from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


PLUGIN_DIR = Path(__file__).resolve().parents[3]
SKILL_DIR = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = SKILL_DIR / "scripts"
TEMPLATE_PATH = SKILL_DIR / "assets" / "review-template.html"
JETBRAINS_PLUGIN = SKILL_DIR / "assets" / "jetbrains-plugin"
HTTP_SERVICE = (
    JETBRAINS_PLUGIN / "src" / "com" / "bytedance" / "easycr" / "EasyCrHttpService.java"
)
PLUGIN_XML = JETBRAINS_PLUGIN / "resources" / "META-INF" / "plugin.xml"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


easy_cr_config = load_module("easy_cr_config", SCRIPTS_DIR / "easy_cr_config.py")
build_review = load_module("easy_cr_build_review", SCRIPTS_DIR / "build_review.py")
configure = load_module("easy_cr_configure", SCRIPTS_DIR / "configure.py")
easy_cr_cli = load_module("easy_cr_cli", SCRIPTS_DIR / "easy_cr_cli.py")
setup_jetbrains = load_module(
    "setup_jetbrains_plugin",
    SCRIPTS_DIR / "setup_jetbrains_plugin.py",
)
setup_vscode = load_module(
    "setup_vscode_extension",
    SCRIPTS_DIR / "setup_vscode_extension.py",
)
install_cli = load_module(
    "easy_cr_install_cli",
    PLUGIN_DIR / "scripts" / "install_cli.py",
)


class PluginManifestTest(unittest.TestCase):
    def test_codex_and_claude_manifests_share_easy_cr_skill(self):
        package = json.loads((PLUGIN_DIR / "package.json").read_text())
        codex = json.loads((PLUGIN_DIR / ".codex-plugin" / "plugin.json").read_text())
        claude = json.loads((PLUGIN_DIR / ".claude-plugin" / "plugin.json").read_text())
        marketplace = json.loads((PLUGIN_DIR / ".claude-plugin" / "marketplace.json").read_text())

        self.assertEqual(package["name"], "easy-cr")
        self.assertEqual(package["bin"], {"easy-cr": "bin/easy-cr"})
        self.assertEqual(codex["name"], "easy-cr")
        self.assertEqual(codex["skills"], "./skills/")
        self.assertEqual(claude["name"], "easy-cr")
        self.assertEqual(marketplace["plugins"][0]["name"], "easy-cr")
        self.assertEqual(marketplace["plugins"][0]["source"], "./")
        self.assertEqual(codex["version"], package["version"])
        self.assertEqual(claude["version"], package["version"])
        self.assertEqual(marketplace["plugins"][0]["version"], package["version"])
        self.assertEqual(easy_cr_cli.VERSION, package["version"])
        self.assertTrue((PLUGIN_DIR / "skills" / "easy-cr" / "SKILL.md").is_file())
        self.assertTrue((PLUGIN_DIR / "bin" / "easy-cr").is_file())


class ConfigurationTest(unittest.TestCase):
    def test_missing_configuration_requests_one_time_choice(self):
        with tempfile.TemporaryDirectory() as temp:
            config = Path(temp) / "config.json"
            semantic, warning = easy_cr_config.resolve_semantic(
                config,
                config_dir=Path(temp),
            )

        self.assertEqual(semantic, {"mode": "none"})
        self.assertIn("尚未配置", warning)

    def test_none_configuration_is_stable_base_mode(self):
        with tempfile.TemporaryDirectory() as temp:
            config = Path(temp) / "config.json"
            easy_cr_config.write_editor("none", config)
            semantic, warning = easy_cr_config.resolve_semantic(
                config,
                config_dir=Path(temp),
            )

            self.assertEqual(json.loads(config.read_text()), {"version": 1, "editor": "none"})
            self.assertEqual(semantic, {"mode": "none"})
            self.assertIsNone(warning)
            self.assertEqual(config.parent.stat().st_mode & 0o777, 0o700)

    def test_goland_configuration_embeds_editor_neutral_payload(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            config = root / "config.json"
            token = root / "goland-token"
            easy_cr_config.write_editor("goland", config)
            token.write_text("A" * 43)
            token.chmod(0o600)

            semantic, warning = easy_cr_config.resolve_semantic(
                config,
                config_dir=root,
            )

        self.assertEqual(warning, None)
        self.assertEqual(semantic["mode"], "editor")
        self.assertEqual(semantic["editor"], "goland")
        self.assertEqual(semantic["displayName"], "GoLand")
        self.assertEqual(semantic["endpoint"], "http://127.0.0.1:64343")
        self.assertEqual(semantic["protocolVersion"], "2")
        self.assertEqual(semantic["token"], "A" * 43)

    def test_idea_configuration_uses_separate_port_and_token(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            config = root / "config.json"
            token = root / "idea-token"
            easy_cr_config.write_editor("idea", config)
            token.write_text("I" * 43)
            token.chmod(0o600)

            semantic, warning = easy_cr_config.resolve_semantic(
                config,
                config_dir=root,
            )

        self.assertIsNone(warning)
        self.assertEqual(semantic["mode"], "editor")
        self.assertEqual(semantic["editor"], "idea")
        self.assertEqual(semantic["endpoint"], "http://127.0.0.1:64344")
        self.assertEqual(semantic["token"], "I" * 43)
        self.assertNotEqual(
            easy_cr_config.EDITOR_DESCRIPTORS["goland"].endpoint,
            easy_cr_config.EDITOR_DESCRIPTORS["idea"].endpoint,
        )

    def test_vscode_configuration_uses_port_64345(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            config = root / "config.json"
            token = root / "vscode-token"
            easy_cr_config.write_editor("vscode", config)
            token.write_text("V" * 43)
            token.chmod(0o600)

            semantic, warning = easy_cr_config.resolve_semantic(
                config,
                config_dir=root,
                repo=root,
            )

        self.assertIsNone(warning)
        self.assertEqual(semantic["mode"], "editor")
        self.assertEqual(semantic["editor"], "vscode")
        self.assertEqual(semantic["endpoint"], "http://127.0.0.1:64345")
        self.assertEqual(semantic["protocolVersion"], "2")
        self.assertEqual(semantic["token"], "V" * 43)
        self.assertEqual(semantic["appName"], "Visual Studio Code")
        self.assertIn("vscode://file", semantic["launchUri"])
        self.assertIn(str(root.resolve()), semantic["launchUri"])

    def test_launch_uri_for_each_editor(self):
        repo = Path("/tmp/demo-repo")
        self.assertIn(
            "vscode://file",
            easy_cr_config.launch_uri_for("vscode", repo) or "",
        )
        self.assertIn(
            "jetbrains://goland/",
            easy_cr_config.launch_uri_for("goland", repo) or "",
        )
        self.assertIn(
            "jetbrains://idea/",
            easy_cr_config.launch_uri_for("idea", repo) or "",
        )
        self.assertIsNone(easy_cr_config.launch_uri_for("none", repo))

    def test_launch_editor_uses_open_a(self):
        with mock.patch.object(easy_cr_config.subprocess, "run") as run:
            run.return_value = mock.Mock(returncode=0, stdout="", stderr="")
            with mock.patch.object(Path, "is_dir", return_value=True):
                app = easy_cr_config.launch_editor("goland", "/tmp/project")
        self.assertEqual(app.name, "GoLand.app")
        command = run.call_args.args[0]
        self.assertEqual(command[:3], ["open", "-a", "GoLand"])
        self.assertTrue(command[3].endswith("/tmp/project") or command[3] == "/tmp/project")

    def test_invalid_or_incomplete_configuration_safely_degrades(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            config = root / "config.json"
            config.write_text('{"version":1,"editor":"goland"}')
            semantic, warning = easy_cr_config.resolve_semantic(
                config,
                config_dir=root,
            )
            self.assertEqual(semantic, {"mode": "none"})
            self.assertIn("GoLand", warning)

            config.write_text('{"version":1,"editor":"idea"}')
            semantic, warning = easy_cr_config.resolve_semantic(
                config,
                config_dir=root,
            )
            self.assertEqual(semantic, {"mode": "none"})
            self.assertIn("IntelliJ IDEA", warning)

            config.write_text('{"version":1,"editor":"notepad"}')
            semantic, warning = easy_cr_config.resolve_semantic(
                config,
                config_dir=root,
            )
            self.assertEqual(semantic, {"mode": "none"})
            self.assertIn("配置无效", warning)

    def test_editor_value_is_exhaustive(self):
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaises(ValueError):
                easy_cr_config.write_editor("notepad", Path(temp) / "config.json")

    def test_status_never_exposes_local_token(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            config = root / "config.json"
            token = root / "goland-token"
            easy_cr_config.write_editor("goland", config)
            token.write_text("S" * 43)
            payload = configure.status_payload(config, config_dir=root)

        serialized = json.dumps(payload)
        self.assertNotIn("S" * 43, serialized)
        self.assertEqual(payload["configuredEditor"], "goland")
        self.assertTrue(payload["golandReady"])
        self.assertTrue(payload["editorReady"])

    def test_legacy_token_path_argument_still_works_for_goland(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            config = root / "config.json"
            token = root / "custom-token"
            easy_cr_config.write_editor("goland", config)
            token.write_text("L" * 43)
            semantic, warning = easy_cr_config.resolve_semantic(config, token)

        self.assertIsNone(warning)
        self.assertEqual(semantic["mode"], "editor")
        self.assertEqual(semantic["token"], "L" * 43)


class TemplateContractTest(unittest.TestCase):
    def test_reference_ui_uses_command_click_and_position_protocol(self):
        template = TEMPLATE_PATH.read_text()

        self.assertIn('id="reference-popover"', template)
        self.assertIn("semanticEnabled", template)
        self.assertIn("!semanticEnabled || !event.metaKey", template)
        self.assertIn("clickByteColumn", template)
        self.assertIn("/api/references", template)
        self.assertIn("/api/open", template)
        self.assertIn("if (payload.opened || references.length <= 1)", template)
        self.assertIn("mode === 'editor' || semantic.mode === 'goland'", template)
        self.assertIn("launchEditorApp", template)
        self.assertIn("isConnectionError", template)
        self.assertIn("正在等待 ${editorName} 扩展就绪", template)
        self.assertNotIn("semantic-toast", template)
        self.assertNotIn("/api/show-usages", template)
        self.assertNotIn("code-identifier", template)

    def test_base_mode_does_not_bind_semantic_requests(self):
        template = TEMPLATE_PATH.read_text()
        self.assertIn("if (!semanticEnabled || !event.metaKey) return;", template)
        self.assertIn("window.getSelection()?.toString()", template)

    def test_jetbrains_adapter_uses_platform_reference_search(self):
        source = HTTP_SERVICE.read_text()
        plugin_xml = PLUGIN_XML.read_text()
        properties = (JETBRAINS_PLUGIN / "resources" / "easycr.properties").read_text()

        self.assertIn("import com.intellij.psi.search.searches.ReferencesSearch;", source)
        self.assertIn("ReferencesSearch.search(", source)
        self.assertNotIn("GoReferencesSearch", source)
        self.assertIn("<depends>com.intellij.modules.lang</depends>", plugin_xml)
        self.assertNotIn("org.jetbrains.plugins.go", plugin_xml)
        self.assertIn("AppIcon.getInstance().requestFocus(frame)", source)
        self.assertIn("if (references.isEmpty())", source)
        self.assertIn("else if (references.size() == 1)", source)
        self.assertIn("openReferenceResult(context, references.get(0))", source)
        self.assertIn('server.createContext("/api/health"', source)
        self.assertIn('"X-Easy-CR-Token"', source)
        self.assertIn('result.addProperty("ready", true)', source)
        self.assertIn('result.addProperty("editor", descriptor.editorId())', source)
        self.assertIn('result.addProperty("protocolVersion", PROTOCOL_VERSION)', source)
        self.assertIn("editor=", properties)
        self.assertIn("port=", properties)

    def test_revision_navigation_allows_tracked_worktree_changes(self):
        source = HTTP_SERVICE.read_text()

        self.assertIn(
            'if ("revision".equals(reviewType)) {\n'
            "            currentFingerprint = headCommit;",
            source,
        )
        self.assertNotIn(
            'runGit(root, "diff", "--quiet", "HEAD", "--")',
            source,
        )
        self.assertNotIn("当前工作区存在 tracked 修改", source)
        self.assertIn(
            'currentFingerprint = sha256(headCommit + "\\n" + diff.stdout());',
            source,
        )

    def test_setup_scripts_support_goland_and_idea(self):
        setup = (SCRIPTS_DIR / "setup_jetbrains_plugin.py").read_text()
        legacy = (SCRIPTS_DIR / "setup_goland_plugin.py").read_text()
        self.assertIn('"goland"', setup)
        self.assertIn('"idea"', setup)
        self.assertEqual(setup_jetbrains.JETBRAINS_EDITORS["goland"].port, 64343)
        self.assertEqual(setup_jetbrains.JETBRAINS_EDITORS["idea"].port, 64344)
        self.assertEqual(
            setup_jetbrains.JETBRAINS_EDITORS["goland"].token_file,
            "goland-token",
        )
        self.assertEqual(
            setup_jetbrains.JETBRAINS_EDITORS["idea"].token_file,
            "idea-token",
        )
        self.assertIn("dataDirectoryName", setup)
        self.assertIn("app_data_directory_name", setup)
        self.assertIn("--editor", legacy)
        self.assertIn("goland", legacy)

    def test_jetbrains_plugins_dir_prefers_product_info(self):
        editor = setup_jetbrains.jetbrains_editor("idea")
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            app = root / "IntelliJ IDEA.app"
            resources = app / "Contents" / "Resources"
            resources.mkdir(parents=True)
            (resources / "product-info.json").write_text(json.dumps({
                "dataDirectoryName": "IntelliJIdea2025.3",
            }))
            support = root / "support"
            # Misleading newer empty stub should lose to product-info.
            (support / "IntelliJIdea2026.1" / "plugins").mkdir(parents=True)
            (support / "IntelliJIdea2025.3" / "options").mkdir(parents=True)
            (support / "IntelliJIdea2025.3" / "plugins").mkdir(parents=True)
            with mock.patch.object(setup_jetbrains, "JETBRAINS_SUPPORT_ROOT", support):
                chosen = setup_jetbrains.newest_plugins_dir(editor, app)
            self.assertEqual(chosen, support / "IntelliJIdea2025.3" / "plugins")

    def test_vscode_extension_scaffold_exists(self):
        extension = SKILL_DIR / "assets" / "vscode-extension"
        package = json.loads((extension / "package.json").read_text())
        protocol = (extension / "src" / "protocol.ts").read_text()
        extension_ts = (extension / "src" / "extension.ts").read_text()
        server = (extension / "src" / "server.ts").read_text()
        setup = (SCRIPTS_DIR / "setup_vscode_extension.py").read_text()

        self.assertEqual(package["name"], "easy-cr")
        self.assertEqual(package["main"], "./dist/extension.js")
        self.assertIn("64345", protocol)
        self.assertIn('EDITOR_ID = "vscode"', protocol)
        self.assertIn("executeReferenceProvider", extension_ts)
        self.assertIn("protocolVersion", server)
        self.assertIn("--install-extension", setup)
        self.assertIn("--force", setup)
        self.assertIn("vscode-token", setup)
        self.assertIn("resolve_code_command", setup)
        self.assertIn("ensure_user_code_shim", setup)

    def test_vscode_setup_discovers_app_bundle_cli(self):
        app_code = Path(
            "/Applications/Visual Studio Code.app/Contents/Resources/app/bin/code"
        )
        with mock.patch.object(setup_vscode.shutil, "which", return_value=None):
            with mock.patch.object(
                setup_vscode,
                "is_usable_code_command",
                side_effect=lambda command: Path(command) == app_code,
            ):
                resolved = setup_vscode.resolve_code_command()
        self.assertEqual(resolved, app_code.resolve())

    def test_vscode_setup_creates_user_path_shim(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            fake_code = root / "Visual Studio Code.app" / "Contents" / "Resources" / "app" / "bin" / "code"
            fake_code.parent.mkdir(parents=True)
            fake_code.write_text("#!/bin/sh\n")
            fake_code.chmod(0o755)
            user_bin = root / ".local" / "bin"
            with mock.patch.object(setup_vscode, "USER_BIN", user_bin):
                with mock.patch.object(setup_vscode.shutil, "which", return_value=None):
                    shim = setup_vscode.ensure_user_code_shim(fake_code)
            self.assertIsNotNone(shim)
            assert shim is not None
            self.assertTrue(shim.is_symlink())
            self.assertEqual(shim.resolve(), fake_code.resolve())
            # Existing unrelated file is left alone.
            shim.unlink()
            shim.write_text("keep")
            with mock.patch.object(setup_vscode, "USER_BIN", user_bin):
                with mock.patch.object(setup_vscode.shutil, "which", return_value=None):
                    again = setup_vscode.ensure_user_code_shim(fake_code)
            self.assertIsNone(again)
            self.assertEqual(shim.read_text(), "keep")


class CliTest(unittest.TestCase):
    def test_non_interactive_init_requires_editor(self):
        with self.assertRaises(SystemExit):
            easy_cr_cli.parse_args(["init", "--non-interactive"])

    def test_cli_accepts_idea_and_vscode_editors(self):
        args = easy_cr_cli.parse_args(["config", "editor", "idea"])
        self.assertEqual(args.editor, "idea")
        args = easy_cr_cli.parse_args(["init", "--editor", "idea", "--non-interactive"])
        self.assertEqual(args.editor, "idea")
        args = easy_cr_cli.parse_args(["config", "editor", "vscode"])
        self.assertEqual(args.editor, "vscode")

    def test_config_editor_reuses_existing_vscode_setup(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            config = root / "config.json"
            token = root / "vscode-token"
            token.write_text("V" * 43)
            token.chmod(0o600)
            listed = subprocess.CompletedProcess(
                args=[],
                returncode=0,
                stdout="bytedance.easy-cr\n",
                stderr="",
            )
            with mock.patch.object(
                easy_cr_cli,
                "resolve_code_command",
                return_value=Path("/Applications/Visual Studio Code.app/code"),
            ):
                with mock.patch.object(easy_cr_cli, "run", return_value=listed) as run:
                    with mock.patch.object(easy_cr_cli, "launch_editor") as launch:
                        installed = easy_cr_cli.configure_editor(
                            "vscode",
                            config_path=config,
                            config_dir=root,
                        )
                        configured = json.loads(config.read_text())["editor"]

        self.assertFalse(installed)
        self.assertEqual(configured, "vscode")
        run.assert_called_once_with(
            [
                "/Applications/Visual Studio Code.app/code",
                "--list-extensions",
            ],
            allow_failure=True,
        )
        launch.assert_not_called()

    def test_config_editor_reuses_existing_idea_setup(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            config = root / "config.json"
            token = root / "idea-token"
            token.write_text("I" * 43)
            token.chmod(0o600)
            with mock.patch.object(
                easy_cr_cli,
                "installed_jetbrains_plugin",
                return_value=root / "plugins" / "easy-cr",
            ):
                with mock.patch.object(easy_cr_cli, "run") as run:
                    with mock.patch.object(easy_cr_cli, "launch_editor") as launch:
                        installed = easy_cr_cli.configure_editor(
                            "idea",
                            config_path=config,
                            config_dir=root,
                        )
                        configured = json.loads(config.read_text())["editor"]

        self.assertFalse(installed)
        self.assertEqual(configured, "idea")
        run.assert_not_called()
        launch.assert_not_called()

    def test_config_editor_installs_incomplete_setup_without_launching(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            config = root / "config.json"
            completed = subprocess.CompletedProcess(
                args=[],
                returncode=0,
                stdout="已安装 Easy CR Visual Studio Code 扩展\n",
                stderr="",
            )
            with mock.patch.object(easy_cr_cli, "run", return_value=completed) as run:
                with mock.patch.object(easy_cr_cli, "launch_editor") as launch:
                    installed = easy_cr_cli.configure_editor(
                        "vscode",
                        config_path=config,
                        config_dir=root,
                    )
                    configured = json.loads(config.read_text())["editor"]

        self.assertTrue(installed)
        self.assertEqual(configured, "vscode")
        self.assertIn(
            str(easy_cr_cli.SETUP_VSCODE_SCRIPT),
            run.call_args.args[0],
        )
        launch.assert_not_called()

    def test_client_detection_uses_codex_app_fallback(self):
        app_codex = Path("/Applications/ChatGPT.app/Contents/Resources/codex")
        with mock.patch.object(easy_cr_cli.shutil, "which", return_value=None):
            with mock.patch.object(Path, "is_file", return_value=True):
                detected = easy_cr_cli.detect_client_commands()
        self.assertEqual(detected["codex"], app_codex)
        self.assertIsNone(detected["claude"])

    def test_codex_marketplace_upsert_preserves_other_plugins(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            home = root / "home"
            repo = home / "GolandProjects" / "easy-cr"
            marketplace = home / ".agents" / "plugins" / "marketplace.json"
            marketplace.parent.mkdir(parents=True)
            marketplace.write_text(json.dumps({
                "name": "personal",
                "interface": {"displayName": "Personal"},
                "plugins": [{
                    "name": "other",
                    "source": {"source": "local", "path": "./plugins/other"},
                    "policy": {
                        "installation": "AVAILABLE",
                        "authentication": "ON_INSTALL",
                    },
                    "category": "Productivity",
                }],
            }))

            changed = easy_cr_cli.upsert_codex_marketplace(repo, marketplace, home)
            unchanged = easy_cr_cli.upsert_codex_marketplace(repo, marketplace, home)
            payload = json.loads(marketplace.read_text())

        self.assertTrue(changed)
        self.assertFalse(unchanged)
        self.assertEqual([item["name"] for item in payload["plugins"]], ["other", "easy-cr"])
        self.assertEqual(
            payload["plugins"][1]["source"]["path"],
            "./GolandProjects/easy-cr",
        )

    def test_status_payload_never_exposes_token(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            config = root / "config.json"
            token = root / "goland-token"
            easy_cr_config.write_editor("goland", config)
            token.write_text("T" * 43)
            token.chmod(0o600)
            with mock.patch.object(
                easy_cr_cli,
                "check_editor_health",
                return_value=(True, None),
            ):
                payload = easy_cr_cli.collect_status(
                    repo_root=PLUGIN_DIR,
                    home=root,
                    config_path=config,
                    config_dir=root,
                    client_commands={"codex": None, "claude": None},
                )

        self.assertNotIn("T" * 43, json.dumps(payload))
        self.assertTrue(payload["goland"]["runtimeReady"])
        self.assertEqual(payload["editor"]["configured"], "goland")
        self.assertTrue(payload["editor"]["runtime"]["runtimeReady"])

    def test_doctor_fails_when_goland_runtime_is_not_ready(self):
        payload = {
            "cli": {"installed": True, "sourceMatches": True},
            "clients": {
                "codex": {"available": False},
                "claude": {"available": False},
            },
            "editor": {
                "configured": "goland",
                "valid": True,
                "runtime": {
                    "displayName": "GoLand",
                    "appInstalled": True,
                    "extensionInstalled": True,
                    "runtimeReady": False,
                    "runtimeError": "connection refused",
                    "token": {"exists": True, "permissionOk": True},
                },
            },
            "goland": {
                "appInstalled": True,
                "extensionInstalled": True,
                "runtimeReady": False,
                "runtimeError": "connection refused",
            },
            "token": {"exists": True, "permissionOk": True},
        }
        checks = easy_cr_cli.build_doctor_checks(payload)
        self.assertTrue(any(item["status"] == "fail" for item in checks))
        self.assertTrue(any(item["name"] == "goland-runtime" for item in checks))

    def test_doctor_checks_idea_runtime(self):
        payload = {
            "cli": {"installed": True, "sourceMatches": True},
            "clients": {
                "codex": {"available": False},
                "claude": {"available": False},
            },
            "editor": {
                "configured": "idea",
                "valid": True,
                "runtime": {
                    "displayName": "IntelliJ IDEA",
                    "appInstalled": True,
                    "extensionInstalled": True,
                    "runtimeReady": True,
                    "runtimeError": None,
                    "token": {"exists": True, "permissionOk": True},
                },
            },
            "goland": {
                "appInstalled": False,
                "extensionInstalled": False,
                "runtimeReady": False,
                "runtimeError": None,
            },
            "token": {"exists": True, "permissionOk": True},
        }
        checks = easy_cr_cli.build_doctor_checks(payload)
        self.assertTrue(any(item["name"] == "idea-runtime" for item in checks))
        self.assertFalse(any(item["status"] == "fail" for item in checks))

    def test_health_rejects_mismatched_editor(self):
        with tempfile.TemporaryDirectory() as temp:
            token = Path(temp) / "goland-token"
            token.write_text("H" * 43)
            token.chmod(0o600)

            class FakeResponse:
                def __enter__(self):
                    return self

                def __exit__(self, *args):
                    return False

                def read(self):
                    return json.dumps({
                        "ready": True,
                        "plugin": "easy-cr",
                        "editor": "idea",
                        "protocolVersion": 2,
                    }).encode()

            with mock.patch.object(
                easy_cr_cli.urllib.request,
                "urlopen",
                return_value=FakeResponse(),
            ):
                ok, error = easy_cr_cli.check_editor_health(
                    "goland",
                    token_path=token,
                    config_dir=Path(temp),
                )
        self.assertFalse(ok)
        self.assertIn("不一致", error or "")


class CliInstallerTest(unittest.TestCase):
    def test_install_creates_and_reuses_expected_symlink(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "easy-cr" / "bin" / "easy-cr"
            source.parent.mkdir(parents=True)
            source.write_text("#!/bin/sh\n")
            destination = root / ".local" / "bin" / "easy-cr"

            first = install_cli.install_symlink(source, destination)
            second = install_cli.install_symlink(source, destination)

        self.assertEqual(first, "created")
        self.assertEqual(second, "unchanged")

    def test_install_updates_old_easy_cr_symlink(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            old_source = root / "plugins" / "easy-cr" / "bin" / "easy-cr"
            new_source = root / "GolandProjects" / "easy-cr" / "bin" / "easy-cr"
            old_source.parent.mkdir(parents=True)
            new_source.parent.mkdir(parents=True)
            old_source.write_text("#!/bin/sh\n")
            new_source.write_text("#!/bin/sh\n")
            destination = root / ".local" / "bin" / "easy-cr"
            destination.parent.mkdir(parents=True)
            destination.symlink_to(old_source)

            result = install_cli.install_symlink(new_source, destination)

        self.assertEqual(result, "updated")

    def test_install_rejects_regular_file_and_unrelated_symlink(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "easy-cr" / "bin" / "easy-cr"
            source.parent.mkdir(parents=True)
            source.write_text("#!/bin/sh\n")
            destination = root / "easy-cr-command"
            destination.write_text("keep")
            with self.assertRaises(RuntimeError):
                install_cli.install_symlink(source, destination)

            destination.unlink()
            unrelated = root / "other" / "bin" / "tool"
            unrelated.parent.mkdir(parents=True)
            unrelated.write_text("#!/bin/sh\n")
            destination.symlink_to(unrelated)
            with self.assertRaises(RuntimeError):
                install_cli.install_symlink(source, destination)


class BuildReviewTest(unittest.TestCase):
    def git(self, repo: Path, *args: str) -> str:
        result = subprocess.run(
            ["git", "-C", str(repo), *args],
            check=True,
            text=True,
            capture_output=True,
        )
        return result.stdout.strip()

    def make_repo(self, root: Path) -> tuple[Path, Path]:
        repo = root / "repo"
        repo.mkdir()
        self.git(repo, "init")
        self.git(repo, "config", "user.name", "Easy CR Test")
        self.git(repo, "config", "user.email", "easy-cr@example.com")
        (repo / "service.go").write_text("package sample\n\nfunc Run() int { return 1 }\n")
        self.git(repo, "add", "service.go")
        self.git(repo, "commit", "-m", "base")
        (repo / "service.go").write_text(
            "package sample\n\nfunc Run() int { return Helper() }\n\nfunc Helper() int { return 2 }\n"
        )
        (repo / "service_test.go").write_text(
            "package sample\n\nfunc ExampleRun() { _ = Run() }\n"
        )
        self.git(repo, "add", "service.go", "service_test.go")
        self.git(repo, "commit", "-m", "add helper")

        manifest = root / "manifest.json"
        manifest.write_text(json.dumps({
            "scope": "测试最新提交",
            "overview_title": "改动概括",
            "summary": "调用 `Helper` 完成结果计算。",
            "boundary": "仅测试插件生成链路。",
            "flow": [
                {"title": "接收调用", "detail": "进入 Run"},
                {"title": "计算结果", "detail": "调用 Helper"},
                {"title": "验证行为", "detail": "运行示例"},
            ],
            "review_points": ["调用顺序", "结果正确"],
            "groups": [
                {
                    "id": "run-helper",
                    "title": "调用结果计算",
                    "summary": "先进入 `Run`，再调用 `Helper`。",
                    "points": ["入口", "计算"],
                    "files": ["service.go"],
                },
                {
                    "id": "verify-result",
                    "title": "验证调用结果",
                    "summary": "使用示例验证完整调用。",
                    "points": ["测试"],
                    "files": ["service_test.go"],
                },
            ],
        }, ensure_ascii=False))
        return repo, manifest

    def build(self, repo: Path, manifest: Path, output: Path, config: Path, token: Path | None = None):
        args = [
            "--repo", str(repo),
            "--base", "HEAD^",
            "--head", "HEAD",
            "--manifest", str(manifest),
            "--output", str(output),
            "--config-file", str(config),
        ]
        if token is not None:
            args.extend(["--token-file", str(token)])
        build_review.main(args)

    def test_base_and_editor_modes_share_business_timeline(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo, manifest = self.make_repo(root)
            config = root / "config.json"

            easy_cr_config.write_editor("none", config)
            base_html = root / "base.html"
            self.build(repo, manifest, base_html, config)
            base = base_html.read_text()
            self.assertIn("调用结果计算", base)
            self.assertLess(base.index("调用结果计算"), base.index("验证调用结果"))
            self.assertIn('"semantic": {"mode": "none"}', base)
            self.assertNotIn("127.0.0.1:64343", base)

            easy_cr_config.write_editor("goland", config)
            token = root / "goland-token"
            token.write_text("B" * 43)
            token.chmod(0o600)
            enhanced_html = root / "enhanced.html"
            self.build(repo, manifest, enhanced_html, config)
            enhanced = enhanced_html.read_text()
            self.assertIn('"mode": "editor"', enhanced)
            self.assertIn('"editor": "goland"', enhanced)
            self.assertIn("http://127.0.0.1:64343", enhanced)
            self.assertIn('"protocolVersion": "2"', enhanced)
            self.assertNotIn('class="code-identifier"', enhanced)
            self.assertNotIn("@@REPORT_JSON@@", enhanced)

            easy_cr_config.write_editor("idea", config)
            idea_token = root / "idea-token"
            idea_token.write_text("C" * 43)
            idea_token.chmod(0o600)
            idea_html = root / "idea.html"
            self.build(repo, manifest, idea_html, config)
            idea = idea_html.read_text()
            self.assertIn('"editor": "idea"', idea)
            self.assertIn("http://127.0.0.1:64344", idea)

    def test_untracked_files_are_not_in_revision_review(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo, manifest = self.make_repo(root)
            (repo / "untracked.go").write_text("package sample\n")
            config = root / "config.json"
            easy_cr_config.write_editor("none", config)
            output = root / "review.html"
            self.build(repo, manifest, output, config)
            self.assertNotIn("untracked.go", output.read_text())


if __name__ == "__main__":
    unittest.main()
