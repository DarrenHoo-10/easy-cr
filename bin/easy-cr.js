#!/usr/bin/env node
"use strict";

const path = require("node:path");
const { runPython } = require("../scripts/python-runner.js");

try {
  const entrypoint = path.join(__dirname, "easy-cr");
  const result = runPython([entrypoint, ...process.argv.slice(2)]);
  if (result.error) throw result.error;
  process.exitCode = result.status === null ? 1 : result.status;
} catch (error) {
  process.stderr.write(`${error.message}\n`);
  process.exitCode = 1;
}
