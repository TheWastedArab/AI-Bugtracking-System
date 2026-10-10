import * as vscode from "vscode";
import { randomBytes } from "node:crypto";

let panel: vscode.WebviewPanel | undefined;

export function activate(context: vscode.ExtensionContext): void {
  context.subscriptions.push(
    vscode.commands.registerCommand("bugTriage.open", () => {
      if (panel) {
        panel.reveal();
        return;
      }
      panel = vscode.window.createWebviewPanel(
        "bugTriage",
        "Bug Triage",
        vscode.ViewColumn.One,
        {
          enableScripts: true,
          retainContextWhenHidden: true,
          localResourceRoots: [
            vscode.Uri.joinPath(context.extensionUri, "media"),
          ],
        },
      );
      const current = panel;
      const nonce = randomBytes(20).toString("hex");
      const script = current.webview.asWebviewUri(
        vscode.Uri.joinPath(context.extensionUri, "media", "app.js"),
      );
      const style = current.webview.asWebviewUri(
        vscode.Uri.joinPath(context.extensionUri, "media", "style.css"),
      );
      current.webview.html = `<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src ${current.webview.cspSource}; script-src 'nonce-${nonce}'; img-src ${current.webview.cspSource}; connect-src 'none';"><link rel="stylesheet" href="${style}"><title>Bug Triage</title></head><body><div id="app"></div><script nonce="${nonce}" src="${script}"></script></body></html>`;
      current.onDidDispose(() => {
        panel = undefined;
      });
      current.webview.onDidReceiveMessage(
        async (message: {
          id: number;
          type: string;
          path?: string;
          method?: string;
          body?: unknown;
          project?: number;
          bug?: number;
          attachment?: number;
          filename?: string;
        }) => {
          try {
            const base = new URL(
              vscode.workspace
                .getConfiguration("bugTriage")
                .get<string>("apiUrl", "http://127.0.0.1:8000"),
            );
            if (
              base.username ||
              base.password ||
              base.search ||
              base.hash ||
              (base.protocol !== "https:" &&
                !(
                  base.protocol === "http:" &&
                  ["localhost", "127.0.0.1", "[::1]"].includes(base.hostname)
                ))
            ) {
              throw new Error(
                "Configure an HTTPS API URL, or use HTTP on localhost.",
              );
            }
            const key = `bugTriage.token:${base.origin}`;
            const token = await context.secrets.get(key);
            const headers: Record<string, string> = token
              ? { Authorization: `Bearer ${token}` }
              : {};
            const send = async (
              path: string,
              method = "GET",
              body?: unknown,
            ): Promise<any> => {
              if (
                !/^\/(auth|projects|admin|notifications)(\/|\?|$)/.test(path) ||
                path.includes("..") ||
                path.includes("\\")
              ) {
                throw new Error("Invalid API path");
              }
              const response = await fetch(new URL(path, base), {
                method,
                headers: { ...headers, "Content-Type": "application/json" },
                body: body === undefined ? undefined : JSON.stringify(body),
                signal: AbortSignal.timeout(15000),
                redirect: "error",
              });
              if (response.status === 401) {
                await context.secrets.delete(key);
              }
              if (!response.ok) {
                const error = (await response.json().catch(() => ({}))) as {
                  detail?: unknown;
                };
                throw new Error(
                  typeof error.detail === "string"
                    ? error.detail
                    : JSON.stringify(error.detail ?? `HTTP ${response.status}`),
                );
              }
              return response.status === 204 ? null : response.json();
            };
            let result: unknown;
            if (message.type === "login") {
              const login = await send("/auth/login", "POST", message.body);
              await context.secrets.store(key, login.access_token);
              result = { signedIn: true };
            } else if (message.type === "logout") {
              try {
                await send("/auth/logout", "POST");
              } finally {
                await context.secrets.delete(key);
              }
              result = null;
            } else if (message.type === "upload") {
              if (
                !Number.isInteger(message.project) ||
                !Number.isInteger(message.bug)
              ) {
                throw new Error("Invalid bug");
              }
              const files = await vscode.window.showOpenDialog({
                canSelectMany: false,
                filters: {
                  "Screenshots and logs": ["png", "jpg", "jpeg", "txt", "log"],
                },
              });
              if (!files?.length) {
                result = { cancelled: true };
              } else {
                const bytes = await vscode.workspace.fs.readFile(files[0]);
                if (bytes.byteLength > 10 * 1024 * 1024) {
                  throw new Error("Maximum attachment size is 10 MB");
                }
                const form = new FormData();
                form.append(
                  "file",
                  new Blob([new Uint8Array(bytes)]),
                  files[0].path.split("/").pop(),
                );
                const response = await fetch(
                  new URL(
                    `/projects/${message.project}/bugs/${message.bug}/attachments`,
                    base,
                  ),
                  {
                    method: "POST",
                    headers,
                    body: form,
                    redirect: "error",
                    signal: AbortSignal.timeout(45000),
                  },
                );
                if (!response.ok) {
                  const error = (await response.json()) as { detail?: string };
                  throw new Error(error.detail ?? "Upload failed");
                }
                result = await response.json();
              }
            } else if (message.type === "download") {
              if (
                ![message.project, message.bug, message.attachment].every(
                  Number.isInteger,
                )
              ) {
                throw new Error("Invalid attachment");
              }
              const response = await fetch(
                new URL(
                  `/projects/${message.project}/bugs/${message.bug}/attachments/${message.attachment}`,
                  base,
                ),
                {
                  headers,
                  redirect: "error",
                  signal: AbortSignal.timeout(15000),
                },
              );
              if (!response.ok) {
                throw new Error("Attachment unavailable");
              }
              const destination = await vscode.window.showSaveDialog({
                saveLabel: "Save attachment",
              });
              if (destination) {
                await vscode.workspace.fs.writeFile(
                  destination,
                  new Uint8Array(await response.arrayBuffer()),
                );
              }
              result = { saved: !!destination };
            } else if (message.type === "request") {
              result = await send(
                message.path ?? "",
                message.method,
                message.body,
              );
            } else {
              throw new Error("Unknown action");
            }
            await current.webview.postMessage({ id: message.id, result });
          } catch (error) {
            await current.webview.postMessage({
              id: message.id,
              error: error instanceof Error ? error.message : "Request failed",
            });
          }
        },
        undefined,
        context.subscriptions,
      );
    }),
  );
}

export function deactivate(): void {
  panel?.dispose();
}
