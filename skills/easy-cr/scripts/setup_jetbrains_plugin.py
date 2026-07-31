#!/usr/bin/env python3
"""Build and install the restricted Easy CR extension into local JetBrains IDEs."""

from __future__ import annotations

import argparse
import json
import os
import secrets
import shutil
import subprocess
import sys
import tempfile
import zipfile
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from easy_cr_config import CONFIG_DIR, candidate_editor_commands
from platform_support import apply_permissions, is_windows


SKILL_DIR = Path(__file__).resolve().parent.parent
PLUGIN_SOURCE = SKILL_DIR / "assets" / "jetbrains-plugin"


def jetbrains_support_root(
    *,
    home: Path | None = None,
    environ: Mapping[str, str] | None = None,
    platform: str | None = None,
) -> Path:
    values = os.environ if environ is None else environ
    resolved_home = (home or Path.home()).expanduser()
    if is_windows(platform):
        app_data = values.get("APPDATA")
        base = Path(app_data) if app_data else resolved_home / "AppData" / "Roaming"
        return base / "JetBrains"
    return resolved_home / "Library" / "Application Support" / "JetBrains"


JETBRAINS_SUPPORT_ROOT = jetbrains_support_root()


@dataclass(frozen=True)
class JetBrainsEditor:
    editor: str
    display_name: str
    default_app: Path
    app_support_pattern: str
    fallback_version_dir: str
    port: int
    token_file: str


JETBRAINS_EDITORS: dict[str, JetBrainsEditor] = {
    "goland": JetBrainsEditor(
        editor="goland",
        display_name="GoLand",
        default_app=Path("/Applications/GoLand.app"),
        app_support_pattern="GoLand*",
        fallback_version_dir="GoLand2026.1",
        port=64343,
        token_file="goland-token",
    ),
    "idea": JetBrainsEditor(
        editor="idea",
        display_name="IntelliJ IDEA",
        default_app=Path("/Applications/IntelliJ IDEA.app"),
        app_support_pattern="IntelliJIdea*",
        fallback_version_dir="IntelliJIdea2026.1",
        port=64344,
        token_file="idea-token",
    ),
}


def jetbrains_editor(editor: str) -> JetBrainsEditor:
    try:
        return JETBRAINS_EDITORS[editor]
    except KeyError as error:
        raise ValueError(
            "editor 仅支持 " + "、".join(sorted(JETBRAINS_EDITORS))
        ) from error


def app_data_directory_name(app: Path) -> str | None:
    """Read the live IDE config directory name from product-info.json."""
    for product_info in (
        app / "product-info.json",
        app / "Contents" / "Resources" / "product-info.json",
    ):
        try:
            payload = json.loads(product_info.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        name = payload.get("dataDirectoryName")
        if isinstance(name, str) and name:
            return name
    return None


def find_jetbrains_app(editor: JetBrainsEditor) -> Path | None:
    """Find an IDE installation root on macOS or Windows."""
    candidates: list[Path] = []
    for command in candidate_editor_commands(editor.editor):
        if command.is_file() and command.parent.name.lower() == "bin":
            candidates.append(command.parent.parent)
    if editor.default_app.is_dir():
        candidates.append(editor.default_app)
    unique: dict[str, Path] = {}
    for candidate in candidates:
        unique.setdefault(os.path.normcase(str(candidate.resolve())), candidate.resolve())
    valid = [
        candidate
        for candidate in unique.values()
        if app_data_directory_name(candidate) is not None
    ]
    if not valid:
        return None
    valid.sort(
        key=lambda path: (path.stat().st_mtime, path.name),
        reverse=True,
    )
    return valid[0]


def plugins_dir_score(plugins_dir: Path) -> tuple[int, int, str]:
    """Prefer real IDE config trees over empty install stubs we may have created."""
    support_dir = plugins_dir.parent
    # A real JetBrains config dir usually contains options/, and often many siblings.
    has_options = 1 if (support_dir / "options").is_dir() else 0
    sibling_count = sum(1 for path in support_dir.iterdir()) if support_dir.is_dir() else 0
    # Higher is better; name is a stable tie-breaker for reverse sort.
    return (has_options, sibling_count, support_dir.name)


def newest_plugins_dir(
    editor: JetBrainsEditor,
    app: Path | None = None,
    *,
    support_root: Path | None = None,
) -> Path:
    """Resolve the plugins directory for the IDE that will actually load the plugin.

    Preference order:
    1. ``dataDirectoryName`` from the selected app's product-info.json
    2. Existing Application Support dirs that look like real IDE configs
    3. Lexicographically newest matching dir
    4. Built-in fallback version dir
    """
    app = app or find_jetbrains_app(editor) or editor.default_app
    root = support_root or JETBRAINS_SUPPORT_ROOT
    data_name = app_data_directory_name(app)
    if data_name:
        return root / data_name / "plugins"

    candidates = list(
        root.glob(f"{editor.app_support_pattern}/plugins")
    )
    if candidates:
        candidates.sort(key=plugins_dir_score, reverse=True)
        return candidates[0]
    return root / editor.fallback_version_dir / "plugins"


def run(command: list[str]) -> None:
    result = subprocess.run(command, text=True, capture_output=True, check=False)
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip() or "command failed")


def build_plugin(editor: JetBrainsEditor, app: Path, output: Path) -> Path:
    if (app / "Contents" / "jbr" / "Contents" / "Home").is_dir():
        java_home = app / "Contents" / "jbr" / "Contents" / "Home"
        lib_root = app / "Contents" / "lib"
    else:
        java_home = app / "jbr"
        lib_root = app / "lib"
    executable_suffix = ".exe" if is_windows() else ""
    javac = java_home / "bin" / f"javac{executable_suffix}"
    java = java_home / "bin" / f"java{executable_suffix}"
    if not javac.is_file() or not java.is_file():
        raise RuntimeError(f"{editor.display_name} JBR tools are missing under {app}")
    sources = sorted((PLUGIN_SOURCE / "src").rglob("*.java"))
    if not sources:
        raise RuntimeError("JetBrains extension sources are missing")
    classes = output / "classes"
    classes.mkdir(parents=True)
    classpath = str(lib_root / "*")
    run([
        str(javac),
        "--add-modules",
        "jdk.httpserver",
        "-parameters",
        "-cp",
        classpath,
        "-d",
        str(classes),
        *map(str, sources),
    ])

    test_sources = sorted((PLUGIN_SOURCE / "testsrc").rglob("*.java"))
    if test_sources:
        test_classes = output / "test-classes"
        test_classes.mkdir()
        test_classpath = os.pathsep.join([str(classes), classpath])
        run([
            str(javac),
            "--add-modules",
            "jdk.httpserver",
            "-cp",
            test_classpath,
            "-d",
            str(test_classes),
            *map(str, test_sources),
        ])
        run([
            str(java),
            "--add-modules",
            "jdk.httpserver",
            "-cp",
            os.pathsep.join([str(test_classes), test_classpath]),
            "com.bytedance.easycr.EasyCrValidationSelfTest",
        ])

    shutil.copytree(PLUGIN_SOURCE / "resources", classes, dirs_exist_ok=True)
    (classes / "easycr.properties").write_text(
        "\n".join([
            f"editor={editor.editor}",
            f"displayName={editor.display_name}",
            f"port={editor.port}",
            f"tokenFile={editor.token_file}",
            "",
        ]),
        encoding="utf-8",
    )
    plugin_jar = output / "easy-cr.jar"
    with zipfile.ZipFile(plugin_jar, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(classes.rglob("*")):
            if path.is_file():
                archive.write(path, path.relative_to(classes).as_posix())
    return plugin_jar


def install(plugin_jar: Path, plugins_dir: Path) -> Path:
    plugins_dir.mkdir(parents=True, exist_ok=True)
    target = plugins_dir / "easy-cr"
    with tempfile.TemporaryDirectory(dir=plugins_dir, prefix=".easy-cr-install-") as temp:
        staged = Path(temp) / "easy-cr"
        (staged / "lib").mkdir(parents=True)
        shutil.copy2(plugin_jar, staged / "lib" / plugin_jar.name)
        backup = plugins_dir / ".easy-cr-install-backup"
        if backup.exists():
            shutil.rmtree(backup)
        if target.exists():
            target.rename(backup)
        staged.rename(target)
        if backup.exists():
            shutil.rmtree(backup)
    return target


def ensure_token(path: Path) -> Path:
    path = path.expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    apply_permissions(path.parent, 0o700)
    if not path.exists():
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w") as stream:
            stream.write(secrets.token_urlsafe(32))
    apply_permissions(path, 0o600)
    return path


def default_token_path(editor: JetBrainsEditor) -> Path:
    return CONFIG_DIR / editor.token_file


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--editor",
        choices=sorted(JETBRAINS_EDITORS),
        required=True,
    )
    parser.add_argument("--app", type=Path, default=None)
    parser.add_argument("--plugins-dir", type=Path, default=None)
    parser.add_argument("--token-file", type=Path, default=None)
    parser.add_argument("--build-only", type=Path)
    args = parser.parse_args(argv)
    args.resolved_editor = jetbrains_editor(args.editor)
    if args.app is None:
        args.app = find_jetbrains_app(args.resolved_editor) or args.resolved_editor.default_app
    if args.plugins_dir is None:
        args.plugins_dir = newest_plugins_dir(args.resolved_editor, args.app)
    if args.token_file is None:
        args.token_file = default_token_path(args.resolved_editor)
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    editor = args.resolved_editor
    try:
        with tempfile.TemporaryDirectory(prefix="easy-cr-build-") as temp:
            plugin_jar = build_plugin(editor, args.app.resolve(), Path(temp))
            if args.build_only:
                args.build_only.expanduser().parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(plugin_jar, args.build_only.expanduser())
                print(args.build_only.expanduser().resolve())
                return 0
            token = ensure_token(args.token_file)
            target = install(plugin_jar, args.plugins_dir.expanduser().resolve())
            print(f"已安装 Easy CR {editor.display_name} 扩展：{target}")
            print(f"本机 token：{token}")
            print(f"请手动重启 {editor.display_name} 一次使新扩展生效。")
            return 0
    except (OSError, RuntimeError) as error:
        print(f"easy-cr setup: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
