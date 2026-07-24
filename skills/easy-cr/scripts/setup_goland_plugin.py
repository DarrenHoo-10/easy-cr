#!/usr/bin/env python3
"""Build and install the restricted Easy CR extension into local GoLand."""

from __future__ import annotations

import argparse
import os
import secrets
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

from easy_cr_config import TOKEN_PATH


SKILL_DIR = Path(__file__).resolve().parent.parent
PLUGIN_SOURCE = SKILL_DIR / "assets" / "goland-plugin"
DEFAULT_GOLAND = Path("/Applications/GoLand.app")


def newest_plugins_dir() -> Path:
    root = Path.home() / "Library" / "Application Support" / "JetBrains"
    candidates = sorted(root.glob("GoLand*/plugins"), reverse=True)
    if candidates:
        return candidates[0]
    return root / "GoLand2026.1" / "plugins"


def run(command: list[str]) -> None:
    result = subprocess.run(command, text=True, capture_output=True, check=False)
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip() or "command failed")


def build_plugin(goland: Path, output: Path) -> Path:
    java_home = goland / "Contents" / "jbr" / "Contents" / "Home"
    javac = java_home / "bin" / "javac"
    java = java_home / "bin" / "java"
    if not javac.is_file() or not java.is_file():
        raise RuntimeError(f"GoLand JBR tools are missing under {goland}")
    sources = sorted((PLUGIN_SOURCE / "src").rglob("*.java"))
    if not sources:
        raise RuntimeError("GoLand extension sources are missing")
    classes = output / "classes"
    classes.mkdir(parents=True)
    classpath = os.pathsep.join([
        str(goland / "Contents" / "lib" / "*"),
        str(goland / "Contents" / "plugins" / "go-plugin" / "lib" / "*"),
    ])
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


def ensure_token(path: Path = TOKEN_PATH) -> Path:
    path = path.expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.parent.chmod(0o700)
    if not path.exists():
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w") as stream:
            stream.write(secrets.token_urlsafe(32))
    path.chmod(0o600)
    return path


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--goland", type=Path, default=DEFAULT_GOLAND)
    parser.add_argument("--plugins-dir", type=Path, default=newest_plugins_dir())
    parser.add_argument("--token-file", type=Path, default=TOKEN_PATH)
    parser.add_argument("--build-only", type=Path)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        with tempfile.TemporaryDirectory(prefix="easy-cr-build-") as temp:
            plugin_jar = build_plugin(args.goland.resolve(), Path(temp))
            if args.build_only:
                args.build_only.expanduser().parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(plugin_jar, args.build_only.expanduser())
                print(args.build_only.expanduser().resolve())
                return 0
            token = ensure_token(args.token_file)
            target = install(plugin_jar, args.plugins_dir.expanduser().resolve())
            print(f"已安装 Easy CR GoLand 扩展：{target}")
            print(f"本机 token：{token}")
            print("请手动重启 GoLand 一次使新扩展生效。")
            return 0
    except (OSError, RuntimeError) as error:
        print(f"easy-cr setup: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
