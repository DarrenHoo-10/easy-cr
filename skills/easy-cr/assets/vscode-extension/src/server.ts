import http from "node:http";
import { timingSafeEqual } from "node:crypto";
import {
  DISPLAY_NAME,
  EDITOR_ID,
  HOST,
  MAX_BODY_BYTES,
  MAX_REFERENCES,
  PORT,
  PROTOCOL_VERSION,
  ProtocolError,
  parseRequest,
  type ReferenceResult,
  type ReferencesResponse,
  type ReviewRequest,
} from "./protocol.js";
import { byteColumnToUtf16, utf16ToByteColumn } from "./position.js";
import {
  resolveSourceFile,
  toWorkspaceRelative,
  validateReviewRequest,
} from "./reviewValidation.js";

export interface EditorBridge {
  isRemote(): boolean;
  workspaceFolders(): readonly string[];
  findReferences(
    absolutePath: string,
    line: number,
    utf16Column: number,
  ): Promise<{ symbol?: string; references: Array<{
    absolutePath: string;
    line: number;
    utf16Column: number;
    preview: string;
  }> }>;
  openAt(absolutePath: string, line: number, utf16Column: number): Promise<void>;
  readLine(absolutePath: string, line: number): Promise<string>;
}

const LOOPBACK_ORIGINS = new Set(["127.0.0.1", "localhost"]);

function isAllowedOrigin(origin: string | undefined): boolean {
  if (origin == null || origin === "null") {
    return true;
  }
  try {
    const url = new URL(origin);
    return url.protocol === "http:" && LOOPBACK_ORIGINS.has(url.hostname);
  } catch {
    return false;
  }
}

function tokenMatches(expected: string, supplied: string | undefined): boolean {
  if (!supplied) {
    return false;
  }
  const left = Buffer.from(expected);
  const right = Buffer.from(supplied);
  return left.length === right.length && timingSafeEqual(left, right);
}

function addCors(headers: http.OutgoingHttpHeaders, origin: string | undefined): void {
  if (origin) {
    headers["Access-Control-Allow-Origin"] = origin;
    headers.Vary = "Origin";
  }
  headers["Access-Control-Allow-Methods"] = "POST, OPTIONS";
  headers["Access-Control-Allow-Headers"] = "Content-Type, X-Easy-CR-Token";
  headers["Access-Control-Allow-Private-Network"] = "true";
  headers["Access-Control-Max-Age"] = "600";
}

async function readBody(req: http.IncomingMessage): Promise<string> {
  const chunks: Buffer[] = [];
  let total = 0;
  for await (const chunk of req) {
    const buffer = Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk);
    total += buffer.length;
    if (total > MAX_BODY_BYTES) {
      throw new ProtocolError(400, "请求体过大");
    }
    chunks.push(buffer);
  }
  return Buffer.concat(chunks).toString("utf8");
}

function sendJson(
  res: http.ServerResponse,
  status: number,
  payload: unknown,
  origin: string | undefined,
): void {
  const body = Buffer.from(JSON.stringify(payload), "utf8");
  const headers: http.OutgoingHttpHeaders = {
    "Content-Type": "application/json; charset=utf-8",
    "Cache-Control": "no-store",
    "Content-Length": body.length,
  };
  addCors(headers, origin);
  res.writeHead(status, headers);
  res.end(body);
}

export class EasyCrServer {
  private server: http.Server | null = null;
  private readonly token: string;
  private readonly bridge: EditorBridge;

  constructor(token: string, bridge: EditorBridge) {
    this.token = token;
    this.bridge = bridge;
  }

  async start(): Promise<void> {
    if (this.bridge.isRemote()) {
      throw new Error("Easy CR VS Code adapter 不支持远程窗口");
    }
    await new Promise<void>((resolve, reject) => {
      const server = http.createServer((req, res) => {
        void this.handle(req, res);
      });
      server.once("error", reject);
      server.listen(PORT, HOST, () => {
        this.server = server;
        resolve();
      });
    });
  }

  async stop(): Promise<void> {
    const server = this.server;
    this.server = null;
    if (!server) {
      return;
    }
    await new Promise<void>((resolve, reject) => {
      server.close((error) => {
        if (error) {
          reject(error);
          return;
        }
        resolve();
      });
    });
  }

  private async handle(req: http.IncomingMessage, res: http.ServerResponse): Promise<void> {
    const origin = req.headers.origin;
    if (!isAllowedOrigin(typeof origin === "string" ? origin : undefined)) {
      sendJson(res, 403, { error: "不允许的请求来源" }, undefined);
      return;
    }
    if (req.method === "OPTIONS") {
      const headers: http.OutgoingHttpHeaders = {};
      addCors(headers, typeof origin === "string" ? origin : undefined);
      res.writeHead(204, headers);
      res.end();
      return;
    }
    if (req.method !== "POST") {
      sendJson(res, 405, { error: "只支持 POST" }, typeof origin === "string" ? origin : undefined);
      return;
    }
    const contentType = req.headers["content-type"];
    if (typeof contentType !== "string" || !contentType.toLowerCase().startsWith("application/json")) {
      sendJson(
        res,
        400,
        { error: "Content-Type 必须为 application/json" },
        typeof origin === "string" ? origin : undefined,
      );
      return;
    }

    try {
      if (req.url === "/api/health") {
        const headerToken = req.headers["x-easy-cr-token"];
        if (!tokenMatches(this.token, typeof headerToken === "string" ? headerToken : undefined)) {
          throw new ProtocolError(401, "无效 token");
        }
        sendJson(
          res,
          200,
          {
            ready: true,
            plugin: "easy-cr",
            editor: EDITOR_ID,
            protocolVersion: PROTOCOL_VERSION,
          },
          typeof origin === "string" ? origin : undefined,
        );
        return;
      }

      const body = await readBody(req);
      if (req.url === "/api/references") {
        const result = await this.handleReferences(body);
        sendJson(res, 200, result, typeof origin === "string" ? origin : undefined);
        return;
      }
      if (req.url === "/api/open") {
        const result = await this.handleOpen(body);
        sendJson(res, 200, result, typeof origin === "string" ? origin : undefined);
        return;
      }
      sendJson(res, 404, { error: "未知接口" }, typeof origin === "string" ? origin : undefined);
    } catch (error) {
      if (error instanceof ProtocolError) {
        sendJson(
          res,
          error.status,
          { error: error.message },
          typeof origin === "string" ? origin : undefined,
        );
        return;
      }
      const message = error instanceof Error ? error.message : String(error);
      sendJson(
        res,
        500,
        { error: `${DISPLAY_NAME} 处理失败：${message}` },
        typeof origin === "string" ? origin : undefined,
      );
    }
  }

  private async authenticatedRequest(body: string): Promise<{
    request: ReviewRequest;
    root: string;
    target: string;
  }> {
    const request = parseRequest(body);
    if (!tokenMatches(this.token, request.token)) {
      throw new ProtocolError(400, "无效 token，请重新生成评审页");
    }
    const { root, target } = await validateReviewRequest(
      request,
      this.bridge.workspaceFolders(),
    );
    return { request, root, target };
  }

  private async handleOpen(body: string): Promise<{ opened: true }> {
    const { request, target } = await this.authenticatedRequest(body);
    const lineText = await this.bridge.readLine(target, request.line);
    const utf16Column = byteColumnToUtf16(lineText, request.column);
    await this.bridge.openAt(target, request.line, utf16Column);
    return { opened: true };
  }

  private async handleReferences(body: string): Promise<ReferencesResponse> {
    const { request, root, target } = await this.authenticatedRequest(body);
    const lineText = await this.bridge.readLine(target, request.line);
    const utf16Column = byteColumnToUtf16(lineText, request.column);
    const query = await this.bridge.findReferences(target, request.line, utf16Column);

    const unique = new Map<string, ReferenceResult>();
    for (const item of query.references) {
      let absolutePath: string;
      try {
        absolutePath = await resolveSourceFile(root, toWorkspaceRelative(root, item.absolutePath));
      } catch {
        continue;
      }
      const previewLine = item.preview || (await this.bridge.readLine(absolutePath, item.line));
      const byteColumn = utf16ToByteColumn(previewLine, item.utf16Column);
      let preview = previewLine.trim().replace(/\t/g, " ");
      if (preview.length > 180) {
        preview = `${preview.slice(0, 177)}...`;
      }
      const relative = toWorkspaceRelative(root, absolutePath);
      const key = `${relative}:${item.line}:${byteColumn}`;
      if (!unique.has(key)) {
        unique.set(key, {
          path: relative,
          line: item.line,
          column: byteColumn,
          preview,
        });
      }
      if (unique.size >= MAX_REFERENCES) {
        break;
      }
    }

    const references = [...unique.values()].sort((left, right) => {
      if (left.path !== right.path) {
        return left.path.localeCompare(right.path);
      }
      if (left.line !== right.line) {
        return left.line - right.line;
      }
      return left.column - right.column;
    });

    let opened = false;
    if (references.length === 0) {
      await this.bridge.openAt(target, request.line, utf16Column);
      opened = true;
    } else if (references.length === 1) {
      const only = references[0]!;
      const absolute = await resolveSourceFile(root, only.path);
      const openLine = await this.bridge.readLine(absolute, only.line);
      await this.bridge.openAt(absolute, only.line, byteColumnToUtf16(openLine, only.column));
      opened = true;
    }

    const response: ReferencesResponse = {
      opened,
      references,
    };
    if (query.symbol) {
      response.symbol = query.symbol;
    }
    return response;
  }
}
