import assert from "node:assert/strict";
import test from "node:test";
import { ProtocolError, parseRequest, validateReviewInputs } from "../out/protocol.js";

test("parseRequest accepts valid payload", () => {
  const request = parseRequest(JSON.stringify({
    token: "t".repeat(32),
    projectPath: "/repo",
    reviewType: "revision",
    fingerprint: "abc",
    base: "HEAD^",
    context: 10,
    filePath: "src/a.ts",
    line: 3,
    column: 4,
  }));
  assert.equal(request.filePath, "src/a.ts");
  assert.equal(request.line, 3);
});

test("parseRequest rejects bad review type and bounds", () => {
  assert.throws(
    () => parseRequest(JSON.stringify({
      token: "t".repeat(32),
      projectPath: "/repo",
      reviewType: "branch",
      fingerprint: "abc",
      base: "HEAD^",
      context: 10,
      filePath: "src/a.ts",
      line: 3,
      column: 4,
    })),
    ProtocolError,
  );
  assert.throws(() => validateReviewInputs("bad revision!", 1, 1, 10), ProtocolError);
  assert.throws(() => validateReviewInputs("HEAD", 0, 1, 10), ProtocolError);
});
