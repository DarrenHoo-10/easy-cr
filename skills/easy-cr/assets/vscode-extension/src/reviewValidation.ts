import { createHash } from "node:crypto";
import { execFile } from "node:child_process";
import { realpath, stat } from "node:fs/promises";
import path from "node:path";
import { promisify } from "node:util";
import { ProtocolError, type ReviewRequest, type ReviewType } from "./protocol.js";

const execFileAsync = promisify(execFile);

export async function resolveWorkspaceRoot(
  projectPath: string,
  workspaceFolders: readonly string[],
): Promise<string> {
  let requested: string;
  try {
    requested = await realpath(projectPath);
  } catch {
    throw new ProtocolError(409, `VS Code 未打开项目：${projectPath}`);
  }
  for (const folder of workspaceFolders) {
    try {
      const resolved = await realpath(folder);
      if (resolved === requested) {
        return resolved;
      }
    } catch {
      // Ignore unreadable folders.
    }
  }
  throw new ProtocolError(409, `VS Code 未打开项目：${requested}`);
}

export async function resolveSourceFile(root: string, relativePath: string): Promise<string> {
  if (!relativePath || relativePath.includes("\0")) {
    throw new ProtocolError(400, "文件路径非法");
  }
  const normalized = path.normalize(path.join(root, relativePath));
  if (normalized !== root && !normalized.startsWith(root + path.sep)) {
    throw new ProtocolError(400, "目标必须是仓库内已有文件");
  }
  let target: string;
  try {
    target = await realpath(normalized);
  } catch {
    throw new ProtocolError(400, "目标必须是仓库内已有文件");
  }
  if (target !== root && !target.startsWith(root + path.sep)) {
    throw new ProtocolError(400, "目标必须是仓库内已有文件");
  }
  const info = await stat(target);
  if (!info.isFile()) {
    throw new ProtocolError(400, "目标必须是仓库内已有文件");
  }
  return target;
}

async function runGit(root: string, args: string[]): Promise<string> {
  try {
    const { stdout } = await execFileAsync(
      "git",
      ["-C", root, "-c", "core.quotePath=false", ...args],
      {
        maxBuffer: 20 * 1024 * 1024,
        encoding: "utf8",
      },
    );
    return stdout;
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    throw new ProtocolError(409, `Git 校验失败：${message}`);
  }
}

function sha256(value: string): string {
  return createHash("sha256").update(value, "utf8").digest("hex");
}

export async function validateReviewFingerprint(
  root: string,
  reviewType: ReviewType,
  fingerprint: string,
  base: string,
  context: number,
): Promise<void> {
  const headCommit = (await runGit(root, ["rev-parse", "HEAD"])).trim();
  let currentFingerprint: string;
  if (reviewType === "revision") {
    currentFingerprint = headCommit;
  } else if (reviewType === "worktree") {
    const diff = await runGit(root, [
      "diff",
      "--no-ext-diff",
      "--find-renames",
      `--unified=${context}`,
      base,
      "--",
    ]);
    currentFingerprint = sha256(`${headCommit}\n${diff}`);
  } else {
    throw new ProtocolError(400, "reviewType 非法");
  }
  if (currentFingerprint !== fingerprint) {
    throw new ProtocolError(409, "评审版本与当前工作区不一致，请重新生成评审页");
  }
}

export async function validateReviewRequest(
  request: ReviewRequest,
  workspaceFolders: readonly string[],
): Promise<{ root: string; target: string }> {
  const root = await resolveWorkspaceRoot(request.projectPath, workspaceFolders);
  await validateReviewFingerprint(
    root,
    request.reviewType,
    request.fingerprint,
    request.base,
    request.context,
  );
  const target = await resolveSourceFile(root, request.filePath);
  return { root, target };
}

export function toWorkspaceRelative(root: string, absolutePath: string): string {
  return path.relative(root, absolutePath).split(path.sep).join("/");
}
