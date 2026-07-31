"use strict";

const { spawnSync } = require("node:child_process");

function candidates() {
  const configured = process.env.EASY_CR_PYTHON;
  const values = [];
  if (configured) values.push({ command: configured, prefix: [] });
  if (process.platform === "win32") {
    values.push(
      { command: "py", prefix: ["-3"] },
      { command: "python", prefix: [] },
      { command: "python3", prefix: [] },
    );
  } else {
    values.push(
      { command: "python3", prefix: [] },
      { command: "python", prefix: [] },
    );
  }
  return values;
}

function resolvePython() {
  for (const candidate of candidates()) {
    const probe = spawnSync(
      candidate.command,
      [...candidate.prefix, "-X", "utf8", "-c", "import sys; raise SystemExit(sys.version_info < (3, 10))"],
      { stdio: "ignore", windowsHide: true },
    );
    if (probe.status === 0) return candidate;
  }
  throw new Error(
    "Easy CR requires Python 3.10+. Install Python and ensure py, python, or python3 is available in PATH.",
  );
}

function runPython(args, options = {}) {
  const python = resolvePython();
  return spawnSync(
    python.command,
    [...python.prefix, "-X", "utf8", ...args],
    {
      stdio: options.stdio || "inherit",
      cwd: options.cwd,
      env: { ...process.env, PYTHONUTF8: "1" },
      windowsHide: false,
    },
  );
}

if (require.main === module) {
  try {
    const result = runPython(process.argv.slice(2));
    if (result.error) throw result.error;
    process.exitCode = result.status === null ? 1 : result.status;
  } catch (error) {
    process.stderr.write(`${error.message}\n`);
    process.exitCode = 1;
  }
}

module.exports = { candidates, resolvePython, runPython };
