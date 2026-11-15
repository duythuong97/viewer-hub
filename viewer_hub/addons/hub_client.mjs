// Viewer Hub: one Node addon reading another (docs/plans/addon-interop.md §3), the Node side of addons/sdk.py.
//
// The Hub passes the path of this file in VIEWER_HUB_NODE_SDK, so the network code lives in the Hub, not in the addon:
//
//   import { pathToFileURL } from "node:url";
//   const hub = await import(pathToFileURL(process.env.VIEWER_HUB_NODE_SDK ?? "./.sdk/node/hub_client.mjs").href);
//   const reply = await hub.call("svn", "svn_log", { repo: "core", limit: 20 });   // addon.json "uses": {"svn": …}
//
//   // serving an export (addon.json "exports"): in the addon's HTTP server, for POST /export/<name>
//   const handled = await hub.serveExport(request, response, { svn_log: async (params) => ({ items: [] }) });
//
// call() rejects with a CallError {code, message, status}: dependency_missing, dependency_incompatible, export_unknown,
// bad_params, bad_reply, dependency_unavailable, call_depth, forbidden. Without a Hub (the addon's tests) it answers
// with fake(id, export, reply) or the "example" of .sdk/addons/<id>.json (VIEWER_HUB_FAKE_EXPORTS: another folder).
import { request as httpRequest } from "node:http";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { AsyncLocalStorage } from "node:async_hooks";

export const CALLER_HEADER = "x-viewer-hub-caller";
export const DEPTH_HEADER = "x-viewer-hub-depth";
const TIMEOUT_MS = 60_000;
const MAX_BODY = 8 * 1024 * 1024;
const depth = new AsyncLocalStorage();
const fakes = new Map();

export class CallError extends Error {
  constructor(code, message, status = 0) {
    super(`${code}: ${message}`);
    this.code = code;
    this.status = status;
    this.reason = message;
  }
}

function readJson(file) {
  try {
    return JSON.parse(readFileSync(file, "utf8"));
  } catch {
    return null;
  }
}

/** Tests: what call(addonId, exportName) answers without a Hub (an Error is thrown instead). */
export function fake(addonId, exportName, reply) {
  fakes.set(`${addonId}/${exportName}`, reply);
}

function folder() {
  return process.env.VIEWER_HUB_ADDON_FOLDER || process.cwd();
}

function fakeCall(addonId, exportName, params) {
  const uses = readJson(join(folder(), "addon.json"))?.uses?.[addonId];
  if (uses && !(uses.exports ?? []).includes(exportName)) {
    throw new CallError("export_unknown", `addon.json chưa khai ${addonId}.${exportName} trong uses`, 403);
  }
  const key = `${addonId}/${exportName}`;
  if (fakes.has(key)) {
    const reply = fakes.get(key);
    if (reply instanceof Error) throw reply;
    return reply;
  }
  const dir = process.env.VIEWER_HUB_FAKE_EXPORTS || join(folder(), ".sdk", "addons");
  const exported = readJson(join(dir, `${addonId}.json`))?.exports?.find((e) => e.name === exportName);
  if (!exported) {
    throw new CallError("dependency_missing",
      `không có Viewer Hub và chưa có contract của ${addonId} (.sdk/addons/${addonId}.json: npm run exports), cũng chưa fake()`);
  }
  return exported.example;
}

/** The reply of another addon's export, through the Hub (only what addon.json "uses" names). */
export async function call(addonId, exportName, params = {}, { timeout = TIMEOUT_MS } = {}) {
  if (params === null || typeof params !== "object" || Array.isArray(params)) {
    throw new CallError("bad_params", "params phải là object");
  }
  const url = process.env.VIEWER_HUB_URL ?? "";
  const caller = process.env.VIEWER_HUB_CALLER_TOKEN ?? "";
  if (!url || !caller) return fakeCall(addonId, exportName, params);
  const match = /^http:\/\/127\.0\.0\.1:(\d+)$/.exec(url);
  if (!match) throw new CallError("forbidden", "VIEWER_HUB_URL phải là http://127.0.0.1:<cổng>");
  const body = Buffer.from(JSON.stringify(params), "utf8");
  const { status, data } = await new Promise((resolve, reject) => {
    const req = httpRequest({
      host: "127.0.0.1", port: Number(match[1]), method: "POST",
      path: `/api/addons/call/${encodeURIComponent(addonId)}/${encodeURIComponent(exportName)}`,
      headers: { "Content-Type": "application/json", "Content-Length": body.length, [CALLER_HEADER]: caller,
        [DEPTH_HEADER]: String(depth.getStore() ?? 0) },
      timeout,
    }, (res) => {
      const chunks = [];
      res.on("data", (c) => chunks.push(c));
      res.on("end", () => resolve({ status: res.statusCode, data: Buffer.concat(chunks).toString("utf8") }));
    });
    req.on("timeout", () => req.destroy(new Error("hết thời gian chờ")));
    req.on("error", (error) => reject(new CallError("dependency_unavailable", `không gọi được Viewer Hub: ${error.message}`)));
    req.end(body);
  });
  let reply = null;
  try {
    reply = data.trim() ? JSON.parse(data) : null;
  } catch {
    throw new CallError("bad_reply", `Viewer Hub trả lời không phải JSON (${status})`, status);
  }
  if (status !== 200) {
    throw new CallError(reply?.error?.code ?? "call_failed", reply?.error?.message ?? `lỗi ${status}`, status);
  }
  return reply;
}

function send(response, status, value) {
  const data = Buffer.from(JSON.stringify(value), "utf8");
  response.writeHead(status, { "Content-Type": "application/json; charset=utf-8", "Content-Length": data.length });
  response.end(data);
}

/** Answers POST /export/<name> with handlers[name](params); false when the request is not an export call. The
 * caller checks the Hub's token first, as for /api and /mcp. A handler throws {code, message, status} for an error. */
export async function serveExport(request, response, handlers) {
  const match = /^\/export\/([a-z0-9_]{1,64})$/.exec(new URL(request.url, "http://x").pathname);
  if (!match || request.method !== "POST") return false;
  const handler = Object.hasOwn(handlers, match[1]) ? handlers[match[1]] : null;
  if (!handler) {
    send(response, 404, { error: { code: "export_unknown", message: `addon chưa có hàm cho export ${match[1]}` } });
    return true;
  }
  const chunks = [];
  let size = 0;
  for await (const chunk of request) {
    size += chunk.length;
    if (size > MAX_BODY) {
      send(response, 413, { error: { code: "too_large", message: "Dữ liệu quá lớn" } });
      return true;
    }
    chunks.push(chunk);
  }
  let params = {};
  try {
    const text = Buffer.concat(chunks).toString("utf8");
    params = text.trim() ? JSON.parse(text) : {};
  } catch {
    send(response, 400, { error: { code: "bad_json", message: "Body không phải JSON" } });
    return true;
  }
  const level = Number.parseInt(request.headers[DEPTH_HEADER] ?? "0", 10) || 0;
  try {
    const result = await depth.run(level, () => handler(params));
    send(response, 200, result ?? {});
  } catch (error) {
    if (error instanceof CallError) {
      send(response, 424, { error: { code: error.code, message: error.reason } });
    } else if (error && typeof error.code === "string" && typeof error.message === "string" && error.status) {
      send(response, error.status, { error: { code: error.code, message: error.message } });
    } else {
      console.error(`export ${match[1]} failed:`, error);
      send(response, 500, { error: { code: "internal", message: "Lỗi trong addon (xem log)" } });
    }
  }
  return true;
}
