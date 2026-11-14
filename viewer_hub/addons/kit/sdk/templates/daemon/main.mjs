// Template daemon addon "my-daemon": a program with its own life that Viewer Hub only starts, stops and talks to.
// Node.js 22+, no dependencies. In a real project this file is usually the bundle of a bigger program (esbuild /
// tsc output) copied here by your build, or merged in with `viewer-hub addon pack <dir> --include <your zip>`.
//
// The contract with Viewer Hub (AGENTS.md "Daemon"):
//   node main.mjs init [--name X]        prepare (config, folders); exit 0. Runs before every start.
//   node main.mjs start [--interval N]   run in the foreground until told to stop (the Hub puts it in background)
//   node main.mjs status --json          one JSON line {running, adminChannel, ...}; exit 0 even when stopped
// and on the admin channel (named pipe / Unix socket, never a TCP port), one JSON line per request:
//   {"method":"GET","path":"/api/health","query":{}}      → {"status":200,"body":{...}}   then close
//   {"method":"EVENTS"}                                   → one {"event","data"} line per event, kept open
// The Hub relays the page's /x/my-daemon/api/<path> to "/api/<path>" here, and /x/my-daemon/api/events to EVENTS.
import fs from "node:fs";
import net from "node:net";
import os from "node:os";
import path from "node:path";

const VERSION = "0.1.0";
const ID = process.env.VIEWER_HUB_ADDON_ID || "my-daemon";
// The Hub gives every addon its own data folder; run by hand (testing) it falls back to ./data.
const DATA = process.env.VIEWER_HUB_ADDON_DATA || path.resolve("data");
const CONFIG = path.join(DATA, "config.json");

function channelPath() {
  if (process.platform === "win32") return `\\\\.\\pipe\\viewer-hub-${ID}-${os.userInfo().username}`;
  const inData = path.join(DATA, "admin.sock");
  return inData.length < 100 ? inData : path.join(os.tmpdir(), `viewer-hub-${ID}-${process.getuid()}.sock`);
}
const CHANNEL = channelPath();

function option(args, name, fallback) {
  const i = args.indexOf(name);
  return i >= 0 && args[i + 1] !== undefined ? args[i + 1] : fallback;
}

function readConfig() {
  try { return JSON.parse(fs.readFileSync(CONFIG, "utf8")); } catch { return {}; }
}

/** One request on the admin channel, as the Hub sends it; null when nothing listens. */
function ask(message, timeout = 2000) {
  return new Promise((resolve) => {
    const socket = net.connect(CHANNEL);
    let text = "";
    const done = (value) => { socket.destroy(); resolve(value); };
    socket.setTimeout(timeout, () => done(null));
    socket.on("error", () => done(null));
    socket.on("data", (chunk) => { text += chunk; });
    socket.on("end", () => { try { done(JSON.parse(text)); } catch { done(null); } });
    socket.on("connect", () => socket.write(JSON.stringify(message) + "\n"));
  });
}

// ── commands ─────────────────────────────────────────────────────────────────────────────────────────────────

function init(args) {
  fs.mkdirSync(DATA, { recursive: true, mode: 0o700 });
  const config = readConfig();
  const name = option(args, "--name", "");
  if (name) config.name = name.slice(0, 80);
  fs.writeFileSync(CONFIG, JSON.stringify({ name: "Bộ đếm", ...config }, null, 2));
  console.log(`init ok: ${DATA}`);
}

async function status(args) {
  const health = await ask({ method: "GET", path: "/api/health", query: {} });
  const info = { running: health?.status === 200, adminChannel: CHANNEL, version: VERSION, data: DATA };
  console.log(args.includes("--json") ? JSON.stringify(info) : `${info.running ? "đang chạy" : "đã dừng"} (${CHANNEL})`);
}

async function start(args) {
  if (await ask({ method: "GET", path: "/api/health", query: {} })) {
    console.log("đã chạy rồi");
    return;
  }
  if (process.platform !== "win32") fs.rmSync(CHANNEL, { force: true }); // a socket left by a crash
  fs.mkdirSync(DATA, { recursive: true, mode: 0o700 });

  const interval = Math.max(1, Number(option(args, "--interval", "5")) || 5);
  const state = { name: readConfig().name || "Bộ đếm", startedAt: new Date().toISOString(), interval, ticks: 0 };
  const watchers = new Set();
  const emit = (event, data) => {
    for (const socket of watchers) socket.write(JSON.stringify({ event, data }) + "\n");
  };
  const timer = setInterval(() => { state.ticks += 1; emit("tick", { ticks: state.ticks }); }, interval * 1000);
  const keepalive = setInterval(() => emit("keepalive", {}), 15000);

  let server;
  const shutdown = () => {
    clearInterval(timer);
    clearInterval(keepalive);
    for (const socket of watchers) socket.end();
    server.close(() => process.exit(0));
    setTimeout(() => process.exit(0), 2000).unref();
  };

  // The API the page uses (through the Hub). Returns [status, body].
  const routes = {
    "GET /api/health": () => [200, { ok: true, version: VERSION }],
    "POST /api/daemon/shutdown": () => { setTimeout(shutdown, 50); return [200, { ok: true }]; },
    "GET /api/state": () => [200, state],
    "POST /api/state/reset": () => { state.ticks = 0; emit("tick", { ticks: 0 }); return [200, state]; },
  };

  server = net.createServer((socket) => {
    let buffer = "";
    socket.setEncoding("utf8");
    socket.on("error", () => watchers.delete(socket));
    socket.on("close", () => watchers.delete(socket));
    socket.on("data", (chunk) => {
      buffer += chunk;
      if (buffer.length > 1024 * 1024) return socket.destroy();
      const end = buffer.indexOf("\n");
      if (end < 0) return;
      let message;
      try { message = JSON.parse(buffer.slice(0, end)); } catch { return socket.end(JSON.stringify({ status: 400, body: { error: { code: "bad_json", message: "Not JSON" } } }) + "\n"); }
      if (message.method === "EVENTS") {
        watchers.add(socket);
        socket.write(JSON.stringify({ event: "keepalive", data: {} }) + "\n"); // the Hub waits for a first line
        return;
      }
      const route = routes[`${message.method} ${message.path}`];
      const [code, body] = route ? route(message) : [404, { error: { code: "not_found", message: "Không tìm thấy" } }];
      socket.end(JSON.stringify({ status: code, body }) + "\n");
    });
  });
  server.on("error", (error) => { console.error(`không mở được kênh quản trị: ${error.message}`); process.exit(1); });
  server.listen(CHANNEL, () => {
    if (process.platform !== "win32") fs.chmodSync(CHANNEL, 0o600); // only this OS user
    console.log(`${state.name}: đang chạy, kênh ${CHANNEL}, chu kỳ ${interval}s`);
  });
  process.on("SIGINT", shutdown);
  process.on("SIGTERM", shutdown);
}

const [command, ...args] = process.argv.slice(2);
const commands = { init, start, status };
if (!commands[command]) {
  console.error("Cách dùng: node main.mjs init|start|status [--json]");
  process.exit(2);
}
await commands[command](args);
