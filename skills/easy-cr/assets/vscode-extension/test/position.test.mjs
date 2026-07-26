import assert from "node:assert/strict";
import test from "node:test";
import { byteColumnToUtf16, utf16ToByteColumn } from "../out/position.js";
import { ProtocolError } from "../out/protocol.js";

test("ascii byte columns map 1:1", () => {
  assert.equal(byteColumnToUtf16("hello", 1), 0);
  assert.equal(byteColumnToUtf16("hello", 3), 2);
  assert.equal(utf16ToByteColumn("hello", 2), 3);
});

test("chinese characters consume three UTF-8 bytes", () => {
  // "// 中文" => bytes: 2 spaces/slashes + space + 中(3) 文(3)
  const line = "// 中文";
  assert.equal(byteColumnToUtf16(line, 4), 3);
  assert.equal(utf16ToByteColumn(line, 3), 4);
});

test("emoji and tabs are handled", () => {
  const line = "a\t😀b";
  // a(1) tab(1) 😀(4) b(1)
  assert.equal(byteColumnToUtf16(line, 1), 0);
  assert.equal(byteColumnToUtf16(line, 2), 1);
  assert.equal(byteColumnToUtf16(line, 3), 2);
  assert.equal(utf16ToByteColumn(line, 2), 3);
});

test("out of range and mid-codepoint columns fail", () => {
  assert.throws(() => byteColumnToUtf16("中", 2), ProtocolError);
  assert.throws(() => byteColumnToUtf16("hi", 10), ProtocolError);
  assert.throws(() => utf16ToByteColumn("hi", 5), ProtocolError);
});
