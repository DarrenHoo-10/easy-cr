import * as vscode from "vscode";
import { execFile } from "node:child_process";
import { homedir } from "node:os";
import { readFile } from "node:fs/promises";
import path from "node:path";
import { promisify } from "node:util";
import { EasyCrServer, type EditorBridge } from "./server.js";
import { DISPLAY_NAME, TOKEN_FILENAME } from "./protocol.js";

const execFileAsync = promisify(execFile);
let server: EasyCrServer | null = null;

class VsCodeBridge implements EditorBridge {
  isRemote(): boolean {
    return Boolean(vscode.env.remoteName);
  }

  workspaceFolders(): readonly string[] {
    return (vscode.workspace.workspaceFolders ?? []).map((folder) => folder.uri.fsPath);
  }

  async readLine(absolutePath: string, line: number): Promise<string> {
    const document = await vscode.workspace.openTextDocument(vscode.Uri.file(absolutePath));
    if (line < 1 || line > document.lineCount) {
      throw new Error("行号超出文件范围");
    }
    return document.lineAt(line - 1).text;
  }

  async openAt(absolutePath: string, line: number, utf16Column: number): Promise<void> {
    const uri = vscode.Uri.file(absolutePath);
    const document = await vscode.workspace.openTextDocument(uri);
    const position = new vscode.Position(Math.max(0, line - 1), Math.max(0, utf16Column));
    const editor = await vscode.window.showTextDocument(document, {
      preview: false,
      preserveFocus: false,
      viewColumn: vscode.ViewColumn.Active,
    });
    editor.selection = new vscode.Selection(position, position);
    editor.revealRange(new vscode.Range(position, position), vscode.TextEditorRevealType.InCenter);
    await focusVsCodeWindow(absolutePath, line, utf16Column + 1);
  }

  async findReferences(
    absolutePath: string,
    line: number,
    utf16Column: number,
  ): Promise<{
    symbol?: string;
    references: Array<{
      absolutePath: string;
      line: number;
      utf16Column: number;
      preview: string;
    }>;
  }> {
    const uri = vscode.Uri.file(absolutePath);
    const document = await vscode.workspace.openTextDocument(uri);
    const position = new vscode.Position(Math.max(0, line - 1), Math.max(0, utf16Column));
    const locations = await vscode.commands.executeCommand<vscode.Location[]>(
      "vscode.executeReferenceProvider",
      document.uri,
      position,
    ) ?? [];

    let symbol: string | undefined;
    try {
      const symbols = await vscode.commands.executeCommand<vscode.DocumentSymbol[]>(
        "vscode.executeDocumentSymbolProvider",
        document.uri,
      );
      symbol = findSymbolName(symbols ?? [], position);
    } catch {
      symbol = undefined;
    }

    const wordRange = document.getWordRangeAtPosition(position);
    if (!symbol && wordRange) {
      symbol = document.getText(wordRange);
    }

    const references = [];
    for (const location of locations) {
      if (location.uri.scheme !== "file") {
        continue;
      }
      let preview = "";
      try {
        const refDocument = await vscode.workspace.openTextDocument(location.uri);
        preview = refDocument.lineAt(location.range.start.line).text;
      } catch {
        preview = "";
      }
      references.push({
        absolutePath: location.uri.fsPath,
        line: location.range.start.line + 1,
        utf16Column: location.range.start.character,
        preview,
      });
    }
    return { symbol, references };
  }
}

function findSymbolName(
  symbols: readonly vscode.DocumentSymbol[],
  position: vscode.Position,
): string | undefined {
  for (const symbol of symbols) {
    if (symbol.range.contains(position)) {
      const child = findSymbolName(symbol.children, position);
      return child ?? symbol.name;
    }
  }
  return undefined;
}

/**
 * Best-effort: bring the local VS Code app to the foreground after navigation.
 * showTextDocument can place the caret correctly while leaving the app behind the browser.
 */
async function focusVsCodeWindow(
  absolutePath: string,
  line: number,
  oneBasedColumn: number,
): Promise<void> {
  if (process.platform === "darwin") {
    try {
      await execFileAsync("osascript", [
        "-e",
        'tell application "Visual Studio Code" to activate',
      ]);
      return;
    } catch {
      // Fall through to URI open.
    }
  }
  try {
    const uri = vscode.Uri.parse(
      `vscode://file${absolutePath}:${Math.max(1, line)}:${Math.max(1, oneBasedColumn)}`,
    );
    await vscode.env.openExternal(uri);
  } catch {
    // Focus is best-effort; navigation already succeeded.
  }
}

async function readToken(): Promise<string> {
  const configRoot = process.platform === "win32"
    ? (process.env.APPDATA ?? path.join(homedir(), "AppData", "Roaming"))
    : (process.env.XDG_CONFIG_HOME ?? path.join(homedir(), ".config"));
  const tokenPath = path.join(configRoot, "easy-cr", TOKEN_FILENAME);
  const token = (await readFile(tokenPath, "utf8")).trim();
  if (!/^[A-Za-z0-9_-]{32,}$/.test(token)) {
    throw new Error("Invalid Easy CR token; run easy-cr config editor vscode");
  }
  return token;
}

export async function activate(context: vscode.ExtensionContext): Promise<void> {
  const bridge = new VsCodeBridge();
  if (bridge.isRemote()) {
    void vscode.window.showWarningMessage(
      "Easy CR VS Code adapter 仅支持本地 Desktop workspace，已在远程窗口中禁用。",
    );
    return;
  }

  try {
    const token = await readToken();
    server = new EasyCrServer(token, bridge);
    await server.start();
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    void vscode.window.showWarningMessage(`${DISPLAY_NAME} Easy CR 扩展未启动：${message}`);
    return;
  }

  context.subscriptions.push({
    dispose: () => {
      void server?.stop();
      server = null;
    },
  });
}

export async function deactivate(): Promise<void> {
  if (server) {
    await server.stop();
    server = null;
  }
}
