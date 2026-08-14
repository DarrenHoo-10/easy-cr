"use strict";

const { runPython } = require("./python-runner.js");

process.env.EASY_CR_DISABLE_HELPER = "1";

const { spawnSync } = require("node:child_process");

const plugin = spawnSync(process.execPath, ["packages/dsh-easy-cr/test.mjs"], {
  cwd: process.cwd(),
  stdio: "inherit",
});
if (plugin.error) throw plugin.error;
if (plugin.status !== 0) process.exit(plugin.status || 1);

for (const args of [
  ["-m", "compileall", "-q", "skills/easy-cr/scripts"],
  ["-m", "unittest", "discover", "-s", "skills/easy-cr/tests", "-v"],
]) {
  const result = runPython(args, { cwd: process.cwd() });
  if (result.error) throw result.error;
  if (result.status !== 0) process.exit(result.status || 1);
}
