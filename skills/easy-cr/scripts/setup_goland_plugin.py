#!/usr/bin/env python3
"""Backward-compatible entrypoint: install the Easy CR extension into GoLand.

Forwarded to ``setup_jetbrains_plugin.py --editor goland``. The legacy
``--goland`` flag is accepted as an alias of ``--app``.
"""

from __future__ import annotations

import sys
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from setup_jetbrains_plugin import main as jetbrains_main  # noqa: E402


def rewrite_argv(argv: list[str]) -> list[str]:
    rewritten = ["--editor", "goland"]
    for index, argument in enumerate(argv):
        if argument == "--goland":
            rewritten.append("--app")
        elif argument.startswith("--goland="):
            rewritten.append("--app=" + argument.split("=", 1)[1])
        else:
            rewritten.append(argument)
    return rewritten


if __name__ == "__main__":
    raise SystemExit(jetbrains_main(rewrite_argv(sys.argv[1:])))
