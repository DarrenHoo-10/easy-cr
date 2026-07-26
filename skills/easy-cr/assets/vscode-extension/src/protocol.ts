export const PROTOCOL_VERSION = 2;
export const EDITOR_ID = "vscode";
export const DISPLAY_NAME = "Visual Studio Code";
export const HOST = "127.0.0.1";
export const PORT = 64345;
export const MAX_BODY_BYTES = 32 * 1024;
export const MAX_REFERENCES = 500;
export const TOKEN_FILENAME = "vscode-token";

export type ReviewType = "revision" | "worktree";

export interface ReviewRequest {
  token: string;
  projectPath: string;
  reviewType: ReviewType;
  fingerprint: string;
  base: string;
  context: number;
  filePath: string;
  line: number;
  column: number;
}

export interface ReferenceResult {
  path: string;
  line: number;
  column: number;
  preview: string;
}

export interface ReferencesResponse {
  symbol?: string;
  opened: boolean;
  references: ReferenceResult[];
}

export class ProtocolError extends Error {
  constructor(
    public readonly status: number,
    message: string,
  ) {
    super(message);
    this.name = "ProtocolError";
  }
}

const REVISION = /^[A-Za-z0-9_./^~{}@:+-]{1,200}$/;

export function validateReviewInputs(
  base: string,
  line: number,
  column: number,
  context: number,
): void {
  if (!REVISION.test(base)) {
    throw new ProtocolError(400, "base revision 非法");
  }
  if (!Number.isInteger(line) || !Number.isInteger(column) || line < 1 || column < 1) {
    throw new ProtocolError(400, "行列必须为正整数");
  }
  if (!Number.isInteger(context) || context < 0 || context > 100) {
    throw new ProtocolError(400, "context 必须在 0 到 100 之间");
  }
}

function stringField(record: Record<string, unknown>, name: string): string {
  const value = record[name];
  if (typeof value !== "string" || value.length === 0) {
    throw new ProtocolError(400, `缺少字段：${name}`);
  }
  return value;
}

function intField(record: Record<string, unknown>, name: string): number {
  const value = record[name];
  if (typeof value !== "number" || !Number.isInteger(value)) {
    throw new ProtocolError(400, `字段必须为整数：${name}`);
  }
  return value;
}

export function parseRequest(body: string): ReviewRequest {
  let payload: unknown;
  try {
    payload = JSON.parse(body);
  } catch {
    throw new ProtocolError(400, "请求体必须是 JSON 对象");
  }
  if (typeof payload !== "object" || payload === null || Array.isArray(payload)) {
    throw new ProtocolError(400, "请求体必须是 JSON 对象");
  }
  const record = payload as Record<string, unknown>;
  const reviewType = stringField(record, "reviewType");
  if (reviewType !== "revision" && reviewType !== "worktree") {
    throw new ProtocolError(400, "reviewType 非法");
  }
  const request: ReviewRequest = {
    token: stringField(record, "token"),
    projectPath: stringField(record, "projectPath"),
    reviewType,
    fingerprint: stringField(record, "fingerprint"),
    base: stringField(record, "base"),
    context: intField(record, "context"),
    filePath: stringField(record, "filePath"),
    line: intField(record, "line"),
    column: intField(record, "column"),
  };
  validateReviewInputs(request.base, request.line, request.column, request.context);
  return request;
}
