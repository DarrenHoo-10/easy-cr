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
install_cli = load_module(
    "easy_cr_install_cli",
    PLUGIN_DIR / "scripts" / "install_cli.py",
)


class PluginManifestTest(unittest.TestCase):
    def test_codex_and_claude_manifests_share_easy_cr_skill(self):
        codex = json.loads((PLUGIN_DIR / ".codex-plugin" / "plugin.json").read_text())
        claude = json.loads((PLUGIN_DIR / ".claude-plugin" / "plugin.json").read_text())
        marketplace = json.loads((PLUGIN_DIR / ".claude-plugin" / "marketplace.json").read_text())

        self.assertEqual(codex["name"], "easy-cr")
        self.assertEqual(codex["skills"], "./skills/")
        self.assertEqual(claude["name"], "easy-cr")
        self.assertEqual(marketplace["plugins"][0]["name"], "easy-cr")
        self.assertEqual(marketplace["plugins"][0]["source"], "./")
        self.assertTrue((PLUGIN_DIR / "skills" / "easy-cr" / "SKILL.md").is_file())
        self.assertTrue((PLUGIN_DIR / "bin" / "easy-cr").is_file())


class ConfigurationTest(unittest.TestCase):
    def test_missing_configuration_requests_one_time_choice(self):
        with tempfile.TemporaryDirectory() as temp:
            config = Path(temp) / "config.json"
            semantic, warning = easy_cr_config.resolve_semantic(config, Path(temp) / "token")

        self.assertEqual(semantic, {"mode": "none"})
        self.assertIn("尚未配置", warning)

    def test_none_configuration_is_stable_base_mode(self):
        with tempfile.TemporaryDirectory() as temp:
            config = Path(temp) / "config.json"
            easy_cr_config.write_editor("none", config)
            semantic, warning = easy_cr_config.resolve_semantic(config, Path(temp) / "token")

            self.assertEqual(json.loads(config.read_text()), {"version": 1, "editor": "none"})
            self.assertEqual(semantic, {"mode": "none"})
            self.assertIsNone(warning)
            self.assertEqual(config.parent.stat().st_mode & 0o777, 0o700)

    def test_goland_configuration_embeds_only_fixed_loopback_api(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            config = root / "config.json"
            token = root / "goland-token"
            easy_cr_config.write_editor("goland", config)
            token.write_text("A" * 43)
            token.chmod(0o600)

            semantic, warning = easy_cr_config.resolve_semantic(config, token)

        self.assertEqual(warning, None)
        self.assertEqual(semantic["mode"], "goland")
        self.assertEqual(semantic["endpoint"], "http://127.0.0.1:64343")
        self.assertEqual(semantic["token"], "A" * 43)

    def test_invalid_or_incomplete_configuration_safely_degrades(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            config = root / "config.json"
            config.write_text('{"version":1,"editor":"goland"}')
            semantic, warning = easy_cr_config.resolve_semantic(config, root / "missing-token")
            self.assertEqual(semantic, {"mode": "none"})
            self.assertIn("GoLand", warning)

            config.write_text('{"version":1,"editor":"vscode"}')
            semantic, warning = easy_cr_config.resolve_semantic(config, root / "missing-token")
            self.assertEqual(semantic, {"mode": "none"})
            self.assertIn("配置无效", warning)

    def test_editor_value_is_exhaustive(self):
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaises(ValueError):
                easy_cr_config.write_editor("vscode", Path(temp) / "config.json")

    def test_status_never_exposes_local_token(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            config = root / "config.json"
            token = root / "token"
            easy_cr_config.write_editor("goland", config)
            token.write_text("S" * 43)
            payload = configure.status_payload(config, token)

        serialized = json.dumps(payload)
        self.assertNotIn("S" * 43, serialized)
        self.assertEqual(payload["configuredEditor"], "goland")
        self.assertTrue(payload["golandReady"])


class TemplateContractTest(unittest.TestCase):
    def test_reference_ui_uses_command_click_and_no_bottom_toast(self):
        template = TEMPLATE_PATH.read_text()

        self.assertIn('id="reference-popover"', template)
        self.assertIn("semantic.mode !== 'goland' || !event.metaKey", template)
        self.assertIn("/api/references", template)
        self.assertIn("/api/open", template)
        self.assertIn("if (references.length <= 1)", template)
        self.assertNotIn("semantic-toast", template)
        self.assertNotIn("/api/show-usages", template)

    def test_base_mode_does_not_bind_semantic_requests(self):
        template = TEMPLATE_PATH.read_text()
        self.assertIn("semantic.mode !== 'goland'", template)
        self.assertIn("window.getSelection()?.toString()", template)

    def test_goland_extension_uses_go_semantic_reference_search(self):
        source = (
            SKILL_DIR
            / "assets"
            / "goland-plugin"
            / "src"
            / "com"
            / "bytedance"
            / "easycr"
            / "EasyCrHttpService.java"
        ).read_text()
        plugin_xml = (
            SKILL_DIR / "assets" / "goland-plugin" / "resources" / "META-INF" / "plugin.xml"
        ).read_text()
        self.assertIn("GoReferencesSearch.search(", source)
        self.assertNotIn("import com.intellij.psi.search.searches.ReferencesSearch;", source)
        self.assertIn("<depends>org.jetbrains.plugins.go</depends>", plugin_xml)
        self.assertIn("AppIcon.getInstance().requestFocus(frame)", source)
        self.assertIn("if (references.isEmpty())", source)
        self.assertIn("else if (references.size() == 1)", source)
        self.assertIn("openReferenceResult(context, references.get(0))", source)
        self.assertIn('server.createContext("/api/health"', source)
        self.assertIn('"X-Easy-CR-Token"', source)
        self.assertIn('result.addProperty("ready", true)', source)


class CliTest(unittest.TestCase):
    def test_non_interactive_init_requires_editor(self):
        with self.assertRaises(SystemExit):
            easy_cr_cli.parse_args(["init", "--non-interactive"])

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
            token = root / "token"
            easy_cr_config.write_editor("goland", config)
            token.write_text("T" * 43)
            with mock.patch.object(
                easy_cr_cli,
                "check_goland_health",
                return_value=(True, None),
            ):
                payload = easy_cr_cli.collect_status(
                    repo_root=PLUGIN_DIR,
                    home=root,
                    config_path=config,
                    token_path=token,
                    client_commands={"codex": None, "claude": None},
                )

        self.assertNotIn("T" * 43, json.dumps(payload))
        self.assertTrue(payload["goland"]["runtimeReady"])

    def test_doctor_fails_when_goland_runtime_is_not_ready(self):
        payload = {
            "cli": {"installed": True, "sourceMatches": True},
            "clients": {
                "codex": {"available": False},
                "claude": {"available": False},
            },
            "editor": {"configured": "goland", "valid": True},
            "goland": {
                "appInstalled": True,
                "extensionInstalled": True,
                "runtimeReady": False,
                "runtimeError": "connection refused",
            },
        }
        checks = easy_cr_cli.build_doctor_checks(payload)
        self.assertTrue(any(item["status"] == "fail" for item in checks))


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

    def build(self, repo: Path, manifest: Path, output: Path, config: Path, token: Path):
        build_review.main([
            "--repo", str(repo),
            "--base", "HEAD^",
            "--head", "HEAD",
            "--manifest", str(manifest),
            "--output", str(output),
            "--config-file", str(config),
            "--token-file", str(token),
        ])

    def test_base_and_goland_modes_share_business_timeline(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo, manifest = self.make_repo(root)
            config = root / "config.json"
            token = root / "token"

            easy_cr_config.write_editor("none", config)
            base_html = root / "base.html"
            self.build(repo, manifest, base_html, config, token)
            base = base_html.read_text()
            self.assertIn("调用结果计算", base)
            self.assertLess(base.index("调用结果计算"), base.index("验证调用结果"))
            self.assertIn('"semantic": {"mode": "none"}', base)
            self.assertNotIn("127.0.0.1:64343", base)

            easy_cr_config.write_editor("goland", config)
            token.write_text("B" * 43)
            token.chmod(0o600)
            enhanced_html = root / "enhanced.html"
            self.build(repo, manifest, enhanced_html, config, token)
            enhanced = enhanced_html.read_text()
            self.assertIn('"mode": "goland"', enhanced)
            self.assertIn("http://127.0.0.1:64343", enhanced)
            self.assertIn('class="code-identifier"', enhanced)
            self.assertNotIn("@@REPORT_JSON@@", enhanced)

    def test_untracked_files_are_not_in_revision_review(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo, manifest = self.make_repo(root)
            (repo / "untracked.go").write_text("package sample\n")
            config = root / "config.json"
            easy_cr_config.write_editor("none", config)
            output = root / "review.html"
            self.build(repo, manifest, output, config, root / "token")
            self.assertNotIn("untracked.go", output.read_text())


if __name__ == "__main__":
    unittest.main()
