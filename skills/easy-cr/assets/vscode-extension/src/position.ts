import { ProtocolError } from "./protocol.js";

/** Convert a 1-based UTF-8 byte column to a 0-based UTF-16 column. */
export function byteColumnToUtf16(lineText: string, utf8ByteColumn: number): number {
  if (!Number.isInteger(utf8ByteColumn) || utf8ByteColumn < 1) {
    throw new ProtocolError(400, "行列必须为正整数");
  }
  const requestedBytes = utf8ByteColumn - 1;
  let consumedBytes = 0;
  let utf16Column = 0;
  for (const char of lineText) {
    if (consumedBytes >= requestedBytes) {
      break;
    }
    const encodedBytes = Buffer.byteLength(char, "utf8");
    if (consumedBytes + encodedBytes > requestedBytes) {
      throw new ProtocolError(400, "列号不在 UTF-8 字符边界");
    }
    consumedBytes += encodedBytes;
    utf16Column += char.length;
  }
  if (consumedBytes !== requestedBytes) {
    throw new ProtocolError(400, "列号超出行范围");
  }
  return utf16Column;
}

/** Convert a 0-based UTF-16 column to a 1-based UTF-8 byte column. */
export function utf16ToByteColumn(lineText: string, utf16Column: number): number {
  if (
    !Number.isInteger(utf16Column)
    || utf16Column < 0
    || utf16Column > lineText.length
  ) {
    throw new ProtocolError(400, "UTF-16 列号超出行范围");
  }
  return Buffer.byteLength(lineText.slice(0, utf16Column), "utf8") + 1;
}
