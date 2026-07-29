from __future__ import annotations

import importlib.util
import json
import os
import re
import socket
import subprocess
import sys
import tempfile
import threading
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
easy_cr_helper = load_module("easy_cr_helper", SCRIPTS_DIR / "easy_cr_helper.py")
build_review = load_module("easy_cr_build_review", SCRIPTS_DIR / "build_review.py")
review_comments = load_module("easy_cr_review_comments", SCRIPTS_DIR / "review_comments.py")
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
        self.assertEqual(codex["version"].split("+", 1)[0], package["version"])
        self.assertEqual(claude["version"], package["version"])
        self.assertEqual(marketplace["plugins"][0]["version"], package["version"])
        self.assertEqual(easy_cr_cli.VERSION, package["version"])
        self.assertTrue((PLUGIN_DIR / "skills" / "easy-cr" / "SKILL.md").is_file())
        self.assertTrue((PLUGIN_DIR / "bin" / "easy-cr").is_file())

    def test_skill_gates_discussion_batches_before_code_changes(self):
        skill = (SKILL_DIR / "SKILL.md").read_text()

        self.assertIn("do not change code yet", skill)
        self.assertIn("Present every such item together", skill)
        self.assertIn("--resolve-batch <batch-id>", skill)
        self.assertIn("未处理 → 处理中 → 已解决", skill)
        self.assertNotIn("Use “补充其他改动”", skill)


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
        self.assertIn("code-identifier", template)
        self.assertIn("/api/references", template)
        self.assertIn("/api/open", template)
        self.assertIn("if (references.length <= 1)", template)
        self.assertIn("mode === 'editor' || semantic.mode === 'goland'", template)
        self.assertIn("launchEditorApp", template)
        self.assertIn("isConnectionError", template)
        self.assertIn("正在等待 ${editorName} 扩展就绪", template)
        self.assertNotIn("semantic-toast", template)
        self.assertNotIn("/api/show-usages", template)

    def test_base_mode_does_not_bind_semantic_requests(self):
        template = TEMPLATE_PATH.read_text()
        self.assertIn("if (!semanticEnabled || !event.metaKey || !identifier) return;", template)
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

    def test_guided_review_is_static_and_comments_write_back_through_helper(self):
        template = TEMPLATE_PATH.read_text()

        self.assertIn('id="chapter-overview"', template)
        self.assertIn('id="guided-review"', template)
        self.assertIn('id="full-diff-view"', template)
        self.assertIn("helperRequest('/api/comments/write'", template)
        self.assertIn("helperRequest('/api/comments/read'", template)
        self.assertIn("helperRequest('/api/reviews/complete'", template)
        self.assertIn('id="complete-review"', template)
        self.assertNotIn("showOpenFilePicker", template)
        self.assertNotIn("createWritable", template)
        self.assertNotIn("exportReviewedCopy", template)
        self.assertNotIn('id="export-comments"', template)
        self.assertIn(review_comments.COMMENTS_START, template)
        self.assertIn(review_comments.COMMENTS_END, template)
        self.assertNotIn("评论将自动写入当前 HTML", template)
        self.assertNotIn("评论已写入 HTML", template)
        self.assertIn("inline-comment-composer", template)
        self.assertIn("inlineAfter", template)
        self.assertIn("values.forEach(comment => {", template)
        self.assertNotIn("values.slice(0, 4).forEach(comment => {", template)
        self.assertIn("main.className = 'mini-comment-main'", template)
        self.assertIn(
            "makeToolbarButton('编辑', () => openInlineEditor(item",
            template,
        )
        self.assertIn(
            "comments = comments.filter(value => value.id !== comment.id)",
            template,
        )
        self.assertNotIn("/api/ai", template)
        self.assertNotIn("fetchExplanation", template)

    def test_report_chrome_uses_single_navy_accent_and_home_button(self):
        template = TEMPLATE_PATH.read_text()

        self.assertIn("--bg:#f5f0e8", template)
        self.assertIn("--primary:#1f3a5f", template)
        self.assertIn("--success:#2e6e55", template)
        self.assertIn("--success-soft:#e3f2e9", template)
        self.assertIn("--danger:#a94b45", template)
        self.assertIn("--danger-soft:#f8e7e5", template)
        self.assertIn("--comment-soft:#fff4c2", template)
        self.assertIn(".metric.plus {", template)
        self.assertIn(".metric.minus {", template)
        self.assertIn(".line.add .line-no", template)
        self.assertIn(".line.del .line-no", template)
        self.assertIn('id="home-button"', template)
        self.assertIn("homeButton.addEventListener('click'", template)
        self.assertNotIn('<div class="boundary">', template)
        self.assertNotIn(".chapter-row.active", template)

    def test_guided_interactions_highlight_references_and_locate_comments(self):
        template = TEMPLATE_PATH.read_text()

        self.assertIn(".step-button.active .step-number", template)
        self.assertIn("semanticReferenceCache", template)
        self.assertIn("scheduleSemanticHighlight", template)
        self.assertIn("lockSemanticHighlight", template)
        self.assertIn("clearSemanticHighlight", template)
        self.assertIn("chapterCommentsFilter", template)
        self.assertIn("scheduleCommentsPopoverOpen(count", template)
        self.assertIn("item.addEventListener('click', () => focusComment(comment))", template)
        self.assertIn("focusCommentElement", template)

    def test_gutter_selection_uses_boundary_clamping(self):
        template = TEMPLATE_PATH.read_text()

        self.assertIn("function normalizeSelectionBoundary", template)
        self.assertNotIn("!startSpan.contains(range.startContainer)", template)
        self.assertIn("closest('.line-no')", template)

    def test_comment_submission_button_and_status_contract(self):
        template = TEMPLATE_PATH.read_text()

        self.assertIn('id="complete-review"', template)
        self.assertIn(">发送评论给 AI</button>", template)
        self.assertIn("COMMENT_STATUS_LABELS", template)
        self.assertIn("pending:'未处理'", template)
        self.assertIn("processing:'处理中'", template)
        self.assertIn("resolved:'已解决'", template)
        self.assertIn("completeReviewButton.classList.add('sent')", template)
        self.assertIn("completeReviewResetTimer = window.setTimeout", template)
        self.assertIn("window.addEventListener('focus', refreshCommentState)", template)
        self.assertIn("comments.some(comment => comment.status === 'processing')", template)
        self.assertIn("}, 1500)", template)
        self.assertNotIn("comment.resolved", template)
        self.assertNotIn("已打开原任务", template)
        self.assertNotIn("重新打开原任务", template)
        self.assertNotIn("已恢复任务", template)

    def test_guided_navigation_has_symmetric_destinations(self):
        template = TEMPLATE_PATH.read_text()

        self.assertIn("function previousStepTarget()", template)
        self.assertIn("function nextStepTarget()", template)
        self.assertIn("上一章节：", template)
        self.assertIn("下一章节：", template)
        self.assertIn("返回章节首页", template)
        self.assertNotIn("next.textContent = '完成本次 CR'", template)


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
            "helper": {
                "launchAgentInstalled": True,
                "tokenExists": True,
                "tokenPermissionOk": True,
                "runtimeReady": True,
            },
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

    def test_comments_command_reads_embedded_comments(self):
        with tempfile.TemporaryDirectory() as temp:
            report = Path(temp) / "review.html"
            payload = {
                "schemaVersion": 2,
                "reportId": "report-1",
                "revision": 1,
                "comments": [{
                    "id": "c1",
                    "scope": "document",
                    "target": {},
                    "body": "需要补充失败分支",
                    "resolved": False,
                    "replies": [],
                }],
            }
            report.write_text(review_comments.replace_comments_block(
                f"<html><body>{review_comments.empty_comments_block('report-1')}</body></html>",
                payload,
            ))

            with mock.patch("sys.stdout") as stdout:
                result = easy_cr_cli.main(["comments", str(report), "--json"])

        self.assertEqual(result, 0)
        rendered = "".join(call.args[0] for call in stdout.write.call_args_list if call.args)
        self.assertIn("需要补充失败分支", rendered)
        self.assertIn('"status": "pending"', rendered)

    def test_comments_command_resolves_one_processing_batch(self):
        with tempfile.TemporaryDirectory() as temp:
            report = Path(temp) / "review.html"
            payload = {
                "schemaVersion": 2,
                "reportId": "report-1",
                "revision": 2,
                "comments": [
                    {
                        "id": "c1",
                        "scope": "document",
                        "target": {},
                        "body": "处理本批",
                        "status": "processing",
                        "aiBatchId": "batch-1",
                        "replies": [],
                    },
                    {
                        "id": "c2",
                        "scope": "document",
                        "target": {},
                        "body": "其他批次",
                        "status": "processing",
                        "aiBatchId": "batch-2",
                        "replies": [],
                    },
                ],
            }
            report.write_text(review_comments.replace_comments_block(
                f"<html>{review_comments.empty_comments_block('report-1')}</html>",
                payload,
            ))

            result = easy_cr_cli.main([
                "comments",
                str(report),
                "--resolve-batch",
                "batch-1",
            ])
            updated = review_comments.extract_comments(report.read_text())

        self.assertEqual(result, 0)
        self.assertEqual(updated["revision"], 3)
        self.assertEqual(updated["comments"][0]["status"], "resolved")
        self.assertEqual(updated["comments"][1]["status"], "processing")

    def test_init_installs_single_helper_service(self):
        args = easy_cr_cli.parse_args([
            "init",
            "--editor",
            "none",
            "--non-interactive",
        ])
        with mock.patch.object(
            easy_cr_cli,
            "detect_client_commands",
            return_value={"codex": None, "claude": None},
        ), mock.patch.object(easy_cr_cli, "install_cli"), mock.patch.object(
            easy_cr_cli,
            "configure_editor",
        ), mock.patch.object(
            easy_cr_cli,
            "install_helper_service",
        ) as install_helper:
            result = easy_cr_cli.handle_init(args)

        self.assertEqual(result, 0)
        install_helper.assert_called_once()


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
    def test_template_replacement_does_not_reprocess_review_content(self):
        rendered = build_review.replace_template(
            "<main>@@DIFFS@@</main>",
            {"DIFFS": "<code>@@TOKEN_FROM_REVIEWED_SOURCE@@</code>"},
        )

        self.assertEqual(
            rendered,
            "<main><code>@@TOKEN_FROM_REVIEWED_SOURCE@@</code></main>",
        )

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

    def make_named_repo(self, root: Path, name: str, path: str, before: str, after: str) -> Path:
        repo = root / name
        repo.mkdir()
        self.git(repo, "init")
        self.git(repo, "config", "user.name", "Easy CR Test")
        self.git(repo, "config", "user.email", "easy-cr@example.com")
        target = repo / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(before)
        self.git(repo, "add", path)
        self.git(repo, "commit", "-m", "base")
        target.write_text(after)
        self.git(repo, "add", path)
        self.git(repo, "commit", "-m", f"update {name}")
        return repo

    def build(
        self,
        repo: Path,
        manifest: Path,
        output: Path,
        config: Path,
        token: Path | None = None,
    ):
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
            self.assertIn('class="code-identifier"', enhanced)
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

    def test_test_diff_is_full_diff_only(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo, manifest = self.make_repo(root)
            config = root / "config.json"
            easy_cr_config.write_editor("none", config)
            output = root / "review.html"
            self.build(repo, manifest, output, config, root / "token")
            rendered = output.read_text()

        chapter_payload = rendered.split("const chapters = ", 1)[1].split(";\n", 1)[0]
        self.assertNotIn("service_test.go", chapter_payload)
        self.assertIn('data-path="service_test.go"', rendered)
        self.assertNotIn("仅测试插件生成链路。", rendered)

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

    def test_v2_manifest_renders_one_chapter_across_three_repositories(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repos = {
                "mission": self.make_named_repo(
                    root, "mission", "service/shared.go",
                    "package mission\n\nfunc Save() bool { return false }\n",
                    "package mission\n\nfunc Save() bool { return true }\n",
                ),
                "promote": self.make_named_repo(
                    root, "promote", "service/shared.go",
                    "package promote\n\nfunc Submit() bool { return false }\n",
                    "package promote\n\nfunc Submit() bool { return true }\n",
                ),
                "cron": self.make_named_repo(
                    root, "cron", "job/retry.go",
                    "package job\n\nfunc Retry() bool { return false }\n",
                    "package job\n\nfunc Retry() bool { return true }\n",
                ),
            }
            manifest = root / "manifest-v2.json"
            manifest.write_text(json.dumps({
                "schema_version": 2,
                "subject": "跨仓库自动提交",
                "scope": "三个仓库的一条业务链路",
                "summary": "按保存、提交、补偿展开。",
                "boundary": "仅用于测试。",
                "repositories": [
                    {"id": key, "label": key, "root": str(repo), "base": "HEAD^", "head": "HEAD"}
                    for key, repo in repos.items()
                ],
                "chapters": [{
                    "id": "auto-submit",
                    "title": "自动提交业务方案",
                    "goal": "跨仓库完成自动提交。",
                    "summary": "保存后提交，失败时补偿。",
                    "steps": [
                        {"id": "save", "title": "保存任务", "explanation": "保存配置。", "code": [
                            {"repo_id": "mission", "path": "service/shared.go", "display_mode": "guided"}
                        ]},
                        {"id": "submit", "title": "提交方案", "explanation": "检查并提交。", "code": [
                            {"repo_id": "promote", "path": "service/shared.go", "display_mode": "compact-context"}
                        ]},
                        {"id": "retry", "title": "失败补偿", "explanation": "补偿失败记录。", "code": [
                            {"repo_id": "cron", "path": "job/retry.go", "display_mode": "diff-only"}
                        ]},
                    ],
                }],
            }, ensure_ascii=False))
            config = root / "config.json"
            easy_cr_config.write_editor("none", config)
            output = root / "multi.html"

            build_review.main([
                "--manifest", str(manifest),
                "--output", str(output),
                "--config-file", str(config),
                "--token-file", str(root / "token"),
            ])
            rendered = output.read_text()

        self.assertIn("自动提交业务方案", rendered)
        self.assertIn("保存任务", rendered)
        self.assertIn("提交方案", rendered)
        self.assertIn("失败补偿", rendered)
        self.assertIn('data-repo-id="mission"', rendered)
        self.assertIn('data-repo-id="promote"', rendered)
        self.assertIn('data-repo-id="cron"', rendered)
        self.assertGreaterEqual(rendered.count("service/shared.go"), 2)
        self.assertIn('"schemaVersion": 2', rendered)
        self.assertIn('"displayMode": "diff-only"', rendered)

    def test_v1_manifest_is_normalized_to_default_repository(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo, manifest = self.make_repo(root)
            config = root / "config.json"
            easy_cr_config.write_editor("none", config)
            output = root / "legacy.html"
            self.build(repo, manifest, output, config, root / "token")
            rendered = output.read_text()

        self.assertIn('"schemaVersion": 2', rendered)
        self.assertIn('"default": {', rendered)
        self.assertIn('data-repo-id="default"', rendered)
        self.assertIn("调用结果计算", rendered)

    def test_unlisted_production_change_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo = root / "repo"
            repo.mkdir()
            self.git(repo, "init")
            self.git(repo, "config", "user.name", "Easy CR Test")
            self.git(repo, "config", "user.email", "easy-cr@example.com")
            (repo / "first.go").write_text("package sample\n\nfunc First() int { return 1 }\n")
            (repo / "second.go").write_text("package sample\n\nfunc Second() int { return 1 }\n")
            self.git(repo, "add", ".")
            self.git(repo, "commit", "-m", "base")
            (repo / "first.go").write_text("package sample\n\nfunc First() int { return 2 }\n")
            (repo / "second.go").write_text("package sample\n\nfunc Second() int { return 2 }\n")
            self.git(repo, "add", ".")
            self.git(repo, "commit", "-m", "change both")
            manifest = root / "manifest.json"
            manifest.write_text(json.dumps({
                "scope": "测试",
                "summary": "只归类第一个文件。",
                "boundary": "测试",
                "flow": [
                    {"title": "开始", "detail": "进入"},
                    {"title": "处理", "detail": "修改"},
                    {"title": "结束", "detail": "完成"},
                ],
                "groups": [{
                    "id": "first",
                    "title": "第一处",
                    "summary": "只展示第一处。",
                    "files": ["first.go"],
                }],
            }))
            config = root / "config.json"
            easy_cr_config.write_editor("none", config)

            with self.assertRaisesRegex(
                ValueError,
                r"second\.go.*未归入业务章节",
            ):
                self.build(
                    repo,
                    manifest,
                    root / "review.html",
                    config,
                    root / "token",
                )

    def test_ranges_cannot_hide_business_diff_lines(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo = self.make_named_repo(
                root,
                "repo",
                "service.go",
                "package sample\n\nfunc Run() int {\n\treturn 1\n}\n",
                "package sample\n\nfunc Run() int {\n\tvalue := 2\n\treturn value\n}\n",
            )
            manifest = root / "manifest.json"
            manifest.write_text(json.dumps({
                "schema_version": 2,
                "scope": "测试",
                "summary": "范围不能遗漏业务 Diff。",
                "boundary": "测试",
                "repositories": [{
                    "id": "repo",
                    "root": str(repo),
                    "base": "HEAD^",
                    "head": "HEAD",
                }],
                "chapters": [{
                    "id": "run",
                    "title": "执行",
                    "steps": [{
                        "id": "calculate",
                        "title": "计算",
                        "explanation": "计算结果。",
                        "code": [{
                            "repo_id": "repo",
                            "path": "service.go",
                            "display_mode": "guided",
                            "ranges": [{"start": 4, "end": 4}],
                        }],
                    }],
                }],
            }))
            config = root / "config.json"
            easy_cr_config.write_editor("none", config)

            with self.assertRaisesRegex(ValueError, "未覆盖业务 Diff"):
                build_review.main([
                    "--manifest", str(manifest),
                    "--output", str(root / "review.html"),
                    "--config-file", str(config),
                    "--token-file", str(root / "token"),
                ])

    def test_guided_ranges_cover_deletions_but_exempt_import_lines(self):
        files = build_review.parse_diff(
            "diff --git a/service.go b/service.go\n"
            "--- a/service.go\n"
            "+++ b/service.go\n"
            "@@ -1,5 +1,6 @@\n"
            " package sample\n"
            " import (\n"
            ' \t"fmt"\n'
            '+\t"strings"\n'
            " )\n"
            "-func Run() int { return 1 }\n"
            "+func Run() int { return 2 }\n"
        )
        repository = build_review.RepositoryReview(
            id="repo",
            label="repo",
            root=Path("/repo"),
            base="HEAD^",
            head="HEAD",
            context=10,
            revision={
                "headCommit": "a" * 40,
                "reviewType": "revision",
                "fingerprint": "a" * 40,
            },
            files=files,
            subject="test",
            author="test",
            authored_at="test",
        )
        reference = build_review.normalize_code_reference(
            {
                "repo_id": "repo",
                "path": "service.go",
                "display_mode": "guided",
                "ranges": [{"start": 5, "end": 6}],
            },
            {"repo": repository},
            "test",
        )
        chapters = [{
            "steps": [{
                "code": [reference],
            }],
        }]

        build_review.validate_diff_coverage(chapters, [repository])

    def test_regeneration_preserves_comments_and_marks_current_iteration(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo = root / "repo"
            repo.mkdir()
            self.git(repo, "init")
            self.git(repo, "config", "user.name", "Easy CR Test")
            self.git(repo, "config", "user.email", "easy-cr@example.com")
            target = repo / "service.go"
            target.write_text("package sample\n")
            self.git(repo, "add", "service.go")
            self.git(repo, "commit", "-m", "base")
            base = self.git(repo, "rev-parse", "HEAD")
            target.write_text(
                "package sample\n\nfunc Value() int { return 2 }\n"
            )
            self.git(repo, "add", "service.go")
            self.git(repo, "commit", "-m", "first change")
            manifest = root / "manifest.json"

            def write_manifest() -> None:
                manifest.write_text(json.dumps({
                    "schema_version": 2,
                    "subject": "迭代评审",
                    "scope": "测试",
                    "summary": "保留历史评论。",
                    "boundary": "测试",
                    "repositories": [{
                        "id": "repo",
                        "root": str(repo),
                        "base": base,
                        "head": "HEAD",
                    }],
                    "chapters": [{
                        "id": "value",
                        "title": "计算值",
                        "steps": [{
                            "id": "return",
                            "title": "返回结果",
                            "explanation": "返回结果。",
                            "code": [{"repo_id": "repo", "path": "service.go"}],
                        }],
                    }],
                }))

            write_manifest()
            config = root / "config.json"
            easy_cr_config.write_editor("none", config)
            output = root / "review.html"
            build_review.main([
                "--manifest", str(manifest),
                "--output", str(output),
                "--config-file", str(config),
                "--token-file", str(root / "token"),
            ])
            first_html = output.read_text()
            first_report_id = json.loads(
                first_html.split("const report = ", 1)[1].split(";\n", 1)[0]
            )["reportId"]
            anchor = re.search(
                r'data-anchor="([^"]+)"[^>]*><span>\+func ',
                first_html,
            )
            self.assertIsNotNone(anchor)
            comments = {
                "schemaVersion": 2,
                "reportId": first_report_id,
                "revision": 1,
                "updatedAt": None,
                "comments": [{
                    "id": "c1",
                    "scope": "code",
                    "target": {
                        "repoId": "repo",
                        "path": "service.go",
                        "startAnchor": anchor.group(1),
                        "endAnchor": anchor.group(1),
                        "lineLabel": "+3",
                    },
                    "quote": "func Value() int { return 2 }",
                    "body": "确认返回值",
                    "status": "processing",
                    "aiBatchId": "batch-1",
                    "replies": [],
                }],
            }
            output.write_text(review_comments.replace_comments_block(
                first_html,
                comments,
            ))

            target.write_text(
                "package sample\n\nconst Offset = 1\n\n"
                "func Value() int { return 2 }\n"
            )
            self.git(repo, "add", "service.go")
            self.git(repo, "commit", "-m", "feedback change")
            write_manifest()
            build_review.main([
                "--manifest", str(manifest),
                "--output", str(output),
                "--config-file", str(config),
                "--token-file", str(root / "token"),
            ])
            second_html = output.read_text()
            migrated = review_comments.extract_comments(second_html)
            second_state = build_review.extract_review_state(second_html)
            second_report_id = migrated["reportId"]
            build_review.main([
                "--manifest", str(manifest),
                "--output", str(output),
                "--config-file", str(config),
                "--token-file", str(root / "token"),
            ])
            third_html = output.read_text()
            third_state = build_review.extract_review_state(third_html)

        self.assertIn("EASY-CR-REVIEW-STATE:START", second_html)
        self.assertIn('class="line add iteration-change"', second_html)
        self.assertNotIn('class="line add iteration-change"', third_html)
        self.assertEqual(second_state["iteration"], 2)
        self.assertEqual(second_state["previousReportId"], first_report_id)
        self.assertEqual(third_state["iteration"], 3)
        self.assertEqual(third_state["previousReportId"], second_report_id)
        self.assertEqual(migrated["comments"][0]["id"], "c1")
        self.assertEqual(migrated["comments"][0]["status"], "processing")
        self.assertTrue(migrated["comments"][0]["target"]["approximate"])
        self.assertNotEqual(migrated["reportId"], first_report_id)


class ReviewCommentsTest(unittest.TestCase):
    def test_comment_parser_ignores_marker_literals_in_runtime_script(self):
        html_text = (
            f"<html>{review_comments.empty_comments_block('report-1')}"
            "<script>const start='<!-- EASY-CR-COMMENTS:START -->';"
            "const end='<!-- EASY-CR-COMMENTS:END -->';</script></html>"
        )

        payload = review_comments.extract_comments(html_text)

        self.assertEqual(payload["reportId"], "report-1")
        self.assertEqual(payload["comments"], [])

    def test_comment_block_escapes_script_terminator(self):
        payload = {
            "schemaVersion": 2,
            "reportId": "report-1",
            "revision": 1,
            "comments": [{"body": "</script><script>alert(1)</script>"}],
        }
        html_text = review_comments.replace_comments_block(
            f"<html>{review_comments.empty_comments_block('report-1')}</html>",
            payload,
        )

        self.assertNotIn("</script><script>alert", html_text)
        extracted = review_comments.extract_comments(html_text)
        self.assertEqual(extracted["comments"][0]["body"], payload["comments"][0]["body"])
        self.assertEqual(extracted["comments"][0]["status"], "pending")

    def test_comment_block_rejects_wrong_report(self):
        html_text = f"<html>{review_comments.empty_comments_block('report-1')}</html>"
        with self.assertRaises(ValueError):
            review_comments.replace_comments_block(html_text, {
                "schemaVersion": 2,
                "reportId": "report-2",
                "revision": 1,
                "comments": [],
            })

    def test_legacy_resolved_boolean_is_migrated_to_status(self):
        payload = {
            "schemaVersion": 2,
            "reportId": "report-1",
            "revision": 1,
            "comments": [
                {"id": "c1", "resolved": False},
                {"id": "c2", "resolved": True},
            ],
        }
        html_text = review_comments.replace_comments_block(
            f"<html>{review_comments.empty_comments_block('report-1')}</html>",
            payload,
        )

        comments = review_comments.extract_comments(html_text)["comments"]

        self.assertEqual(comments[0]["status"], "pending")
        self.assertEqual(comments[1]["status"], "resolved")
        self.assertNotIn("resolved", comments[0])

    def test_mark_batch_resolved_only_updates_matching_processing_comments(self):
        payload = {
            "schemaVersion": 2,
            "reportId": "report-1",
            "revision": 4,
            "comments": [
                {"id": "c1", "status": "processing", "aiBatchId": "batch-1"},
                {"id": "c2", "status": "processing", "aiBatchId": "batch-2"},
                {"id": "c3", "status": "pending", "aiBatchId": None},
            ],
        }

        updated = review_comments.mark_batch_resolved(payload, "batch-1")

        self.assertEqual(updated["revision"], 5)
        self.assertEqual(updated["comments"][0]["status"], "resolved")
        self.assertEqual(updated["comments"][1]["status"], "processing")
        self.assertEqual(updated["comments"][2]["status"], "pending")


class HelperServiceTest(unittest.TestCase):
    def make_report(self, root: Path, report_id: str = "report-1") -> Path:
        artifacts = root / "repo" / ".codex-artifacts"
        artifacts.mkdir(parents=True)
        report = artifacts / "review.html"
        report.write_text(
            f"<html><body>{review_comments.empty_comments_block(report_id)}</body></html>"
        )
        return report

    def test_register_and_write_comments_updates_only_current_html(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            report = self.make_report(root)
            store = easy_cr_helper.HelperStore(root / "config")
            registration = store.register_report({
                "reportId": "report-1",
                "path": str(report),
                "repositoryRoots": [str(root / "repo")],
                "agent": None,
            })
            payload = store.write_comments(
                "report-1",
                registration["reportToken"],
                0,
                [{
                    "id": "c1",
                    "scope": "document",
                    "target": {},
                    "body": "请补充失败分支",
                    "resolved": False,
                    "replies": [],
                }],
            )

            embedded = review_comments.extract_comments(report.read_text())
            rendered = report.read_text()

        self.assertEqual(payload["revision"], 1)
        self.assertEqual(embedded, payload)
        self.assertIn("请补充失败分支", rendered)

    def test_read_comments_returns_latest_embedded_state(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            report = self.make_report(root)
            store = easy_cr_helper.HelperStore(root / "config")
            registration = store.register_report({
                "reportId": "report-1",
                "path": str(report),
                "repositoryRoots": [str(root / "repo")],
                "agent": None,
            })
            written = store.write_comments(
                "report-1",
                registration["reportToken"],
                0,
                [{
                    "id": "c1",
                    "scope": "document",
                    "target": {},
                    "body": "处理中",
                    "status": "processing",
                    "replies": [],
                }],
            )

            payload = store.read_comments(
                "report-1",
                registration["reportToken"],
            )

        self.assertEqual(payload, written)

    def test_write_rejects_stale_revision_and_path_escape(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            report = self.make_report(root)
            store = easy_cr_helper.HelperStore(root / "config")
            registration = store.register_report({
                "reportId": "report-1",
                "path": str(report),
                "repositoryRoots": [str(root / "repo")],
                "agent": None,
            })
            store.write_comments(
                "report-1",
                registration["reportToken"],
                0,
                [],
            )
            with self.assertRaises(easy_cr_helper.ConflictError):
                store.write_comments(
                    "report-1",
                    registration["reportToken"],
                    0,
                    [],
                )

            outside = root / "outside.html"
            outside.write_text(
                f"<html>{review_comments.empty_comments_block('outside')}</html>"
            )
            with self.assertRaises(ValueError):
                store.register_report({
                    "reportId": "outside",
                    "path": str(outside),
                    "repositoryRoots": [str(root / "repo")],
                    "agent": None,
                })

    def test_send_comment_batch_marks_only_pending_comments_processing(self):
        launched: list[tuple[dict, Path]] = []
        opened: list[str] = []
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            report = self.make_report(root)
            store = easy_cr_helper.HelperStore(
                root / "config",
                launcher=lambda agent, path: launched.append((agent, path)),
                client_opener=lambda agent: opened.append(agent["sessionId"]) or True,
            )
            registration = store.register_report({
                "reportId": "report-1",
                "path": str(report),
                "repositoryRoots": [str(root / "repo")],
                "agent": {
                    "client": "codex",
                    "sessionId": "session-1",
                    "cwd": str(root / "repo"),
                },
                "subject": "帐期优化",
            })
            written = store.write_comments(
                "report-1",
                registration["reportToken"],
                0,
                [
                    {
                        "id": "c1",
                        "scope": "document",
                        "target": {},
                        "body": "处理这条",
                        "status": "pending",
                        "replies": [],
                    },
                    {
                        "id": "c2",
                        "scope": "document",
                        "target": {},
                        "body": "不要重复处理",
                        "status": "processing",
                        "aiBatchId": "old-batch",
                        "replies": [],
                    },
                ],
            )

            first = store.complete_review(
                "report-1",
                registration["reportToken"],
                written["revision"],
                ["c1"],
                "batch-1",
            )
            embedded = review_comments.extract_comments(report.read_text())
            with self.assertRaises(ValueError):
                store.complete_review(
                    "report-1",
                    registration["reportToken"],
                    embedded["revision"],
                    ["c1"],
                    "batch-2",
                )

        self.assertEqual(first["status"], "opened")
        self.assertTrue(first["agentStarted"])
        self.assertTrue(first["clientOpened"])
        self.assertEqual(first["comments"]["revision"], 2)
        self.assertEqual(embedded["comments"][0]["status"], "processing")
        self.assertEqual(embedded["comments"][0]["aiBatchId"], "batch-1")
        self.assertEqual(embedded["comments"][1]["aiBatchId"], "old-batch")
        self.assertEqual(len(launched), 1)
        self.assertEqual(opened, ["session-1"])
        self.assertEqual(launched[0][0]["reportSubject"], "帐期优化")
        self.assertEqual(launched[0][0]["reviewBatchId"], "batch-1")
        self.assertEqual(launched[0][0]["reviewCommentIds"], ["c1"])

    def test_send_failure_keeps_comments_pending(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            report = self.make_report(root)
            store = easy_cr_helper.HelperStore(
                root / "config",
                launcher=lambda _agent, _path: (_ for _ in ()).throw(
                    RuntimeError("launch failed")
                ),
            )
            registration = store.register_report({
                "reportId": "report-1",
                "path": str(report),
                "repositoryRoots": [str(root / "repo")],
                "agent": {
                    "client": "codex",
                    "sessionId": "session-1",
                    "cwd": str(root / "repo"),
                },
            })
            written = store.write_comments(
                "report-1",
                registration["reportToken"],
                0,
                [{
                    "id": "c1",
                    "scope": "document",
                    "target": {},
                    "body": "待处理",
                    "status": "pending",
                    "replies": [],
                }],
            )

            with self.assertRaisesRegex(RuntimeError, "launch failed"):
                store.complete_review(
                    "report-1",
                    registration["reportToken"],
                    written["revision"],
                    ["c1"],
                    "batch-1",
                )
            embedded = review_comments.extract_comments(report.read_text())

        self.assertEqual(embedded["revision"], 1)
        self.assertEqual(embedded["comments"][0]["status"], "pending")

    def test_codex_thread_url_and_partial_open_retry(self):
        session_id = "019f88f5-e5d7-7ff1-bac3-7c46ab1fd365"
        self.assertEqual(
            easy_cr_helper.codex_thread_url(session_id),
            f"codex://threads/{session_id}",
        )
        with self.assertRaises(ValueError):
            easy_cr_helper.codex_thread_url("../../settings")

        launched: list[str] = []
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            report = self.make_report(root)
            store = easy_cr_helper.HelperStore(
                root / "config",
                launcher=lambda agent, path: launched.append(agent["sessionId"]),
                client_opener=lambda agent: False,
            )
            registration = store.register_report({
                "reportId": "report-1",
                "path": str(report),
                "repositoryRoots": [str(root / "repo")],
                "agent": {
                    "client": "codex",
                    "sessionId": session_id,
                    "cwd": str(root / "repo"),
                },
            })
            written = store.write_comments(
                "report-1",
                registration["reportToken"],
                0,
                [{
                    "id": "c1",
                    "scope": "document",
                    "target": {},
                    "body": "待处理",
                    "status": "pending",
                    "replies": [],
                }],
            )

            first = store.complete_review(
                "report-1",
                registration["reportToken"],
                written["revision"],
                ["c1"],
                "batch-1",
            )

        self.assertEqual(first["status"], "agent_started")
        self.assertFalse(first["clientOpened"])
        self.assertEqual(launched, [session_id])

    def test_agent_commands_resume_the_originating_session(self):
        report = Path("/repo/.codex-artifacts/review.html")
        codex = easy_cr_helper.agent_command(
            {
                "client": "codex",
                "sessionId": "codex-session",
                "reportSubject": "帐期优化",
                "reviewBatchId": "batch-1",
                "reviewCommentIds": ["c1", "c2"],
            },
            report,
            codex_command=Path("/Applications/Codex"),
        )
        claude = easy_cr_helper.agent_command(
            {"client": "claude", "sessionId": "claude-session"},
            report,
            claude_command=Path("/usr/local/bin/claude"),
        )

        self.assertEqual(codex[:4], [
            "/Applications/Codex",
            "exec",
            "resume",
            "codex-session",
        ])
        self.assertEqual(claude[:4], [
            "/usr/local/bin/claude",
            "--resume",
            "claude-session",
            "--print",
        ])
        self.assertEqual(
            codex[-1],
            (
                "我已完成 CR，请处理「帐期优化」CR 报告中本次发送的 2 条评论"
                f"（批次 batch-1）：{report}"
            ),
        )
        self.assertIn(str(report), claude[-1])

    def test_codex_native_ipc_starts_turn_in_bound_desktop_thread(self):
        session_id = "019f88f5-e5d7-7ff1-bac3-7c46ab1fd365"
        received: list[dict] = []
        with tempfile.TemporaryDirectory() as temp:
            socket_path = Path(temp) / "ipc.sock"
            server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            server.bind(str(socket_path))
            server.listen(1)

            def serve_once() -> None:
                connection, _ = server.accept()
                with connection:
                    initialize = easy_cr_helper._read_ipc_frame(connection)
                    received.append(initialize)
                    easy_cr_helper._write_ipc_frame(
                        connection,
                        {
                            "type": "response",
                            "requestId": initialize["requestId"],
                            "resultType": "success",
                            "method": "initialize",
                            "result": {"clientId": "easy-cr-client"},
                        },
                    )
                    request = easy_cr_helper._read_ipc_frame(connection)
                    received.append(request)
                    easy_cr_helper._write_ipc_frame(
                        connection,
                        {
                            "type": "response",
                            "requestId": request["requestId"],
                            "resultType": "success",
                            "method": request["method"],
                            "result": {"result": {"turn": {"id": "turn-1"}}},
                        },
                    )

            worker = threading.Thread(target=serve_once)
            worker.start()
            result = easy_cr_helper.submit_codex_turn(
                session_id,
                "处理这条评论",
                socket_path=socket_path,
            )
            worker.join(timeout=2)
            server.close()

        self.assertFalse(worker.is_alive())
        self.assertEqual(received[0]["method"], "initialize")
        self.assertEqual(received[0]["params"]["clientType"], "easy-cr")
        request = received[1]
        self.assertEqual(request["method"], "thread-follower-start-turn")
        self.assertEqual(request["version"], 1)
        self.assertEqual(request["sourceClientId"], "easy-cr-client")
        self.assertEqual(request["params"]["conversationId"], session_id)
        self.assertEqual(
            request["params"]["turnStartParams"]["input"],
            [{"type": "text", "text": "处理这条评论"}],
        )
        self.assertEqual(result["resultType"], "success")

    def test_default_launcher_uses_codex_desktop_ipc(self):
        report = Path("/repo/.codex-artifacts/review.html")
        session_id = "019f88f5-e5d7-7ff1-bac3-7c46ab1fd365"
        with mock.patch.object(
            easy_cr_helper,
            "submit_codex_turn",
        ) as submit, mock.patch.object(subprocess, "Popen") as popen:
            easy_cr_helper._default_launcher(
                {
                    "client": "codex",
                    "sessionId": session_id,
                    "reportSubject": "帐期优化",
                    "reviewBatchId": "batch-1",
                    "reviewCommentIds": ["c1"],
                },
                report,
            )

        submit.assert_called_once()
        self.assertEqual(submit.call_args.args[0], session_id)
        self.assertIn("批次 batch-1", submit.call_args.args[1])
        popen.assert_not_called()

    def test_launch_agent_uses_one_fixed_label_and_port(self):
        payload = easy_cr_helper.launch_agent_payload(
            Path("/usr/bin/python3"),
            Path("/plugin/easy_cr_helper.py"),
            Path("/tmp/token"),
        )

        self.assertEqual(
            payload["Label"],
            "com.bytedance.easy-cr.helper",
        )
        self.assertIn("64344", payload["ProgramArguments"])
        self.assertTrue(payload["KeepAlive"])


if __name__ == "__main__":
    unittest.main()
