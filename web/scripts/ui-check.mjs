// UI check runner (started by packaging/ui_check.py): opens each page at each width in the Chrome / Edge installed on the
// machine (headless, DevTools protocol over the WebSocket built into Node 22, no package) and lists layout breakage:
//   - sticks-out: an element runs past the right edge of its box (overlaps or is cut by the parent)
//   - cut: text clipped by overflow hidden without an ellipsis
//   - scroll-x: a column scrolls sideways (a long word widened it), or the whole page does
// Writes <out>/report.json and one screenshot per page and width. Exit code 1 when something is found.
//
// Mark an element that is meant to overflow or scroll sideways with data-ui-check="skip" (graph canvases are skipped).

import { spawn } from "node:child_process";
import { existsSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const config = JSON.parse(readFileSync(process.argv[2], "utf8"));
const HEIGHT = 900;

function findBrowser() {
  const env = process.env.VIEWER_HUB_CHROME;
  if (env) return env;
  const programFiles = [process.env.PROGRAMFILES, process.env["PROGRAMFILES(X86)"], process.env.LOCALAPPDATA].filter(Boolean);
  const candidates = {
    darwin: ["/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
      "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge", "/Applications/Chromium.app/Contents/MacOS/Chromium"],
    win32: programFiles.flatMap((base) => [join(base, "Google/Chrome/Application/chrome.exe"),
      join(base, "Microsoft/Edge/Application/msedge.exe")]),
    linux: ["/usr/bin/google-chrome", "/usr/bin/chromium", "/usr/bin/chromium-browser", "/usr/bin/microsoft-edge"],
  }[process.platform] || [];
  return candidates.find((path) => existsSync(path));
}

function launch(binary, profile) {
  const child = spawn(binary, ["--headless=new", "--remote-debugging-port=0", `--user-data-dir=${profile}`, "--no-first-run",
    "--no-default-browser-check", "--disable-extensions", "--hide-scrollbars", "--window-size=1600,900", "about:blank"],
  { stdio: ["ignore", "ignore", "pipe"] });
  return new Promise((resolve, reject) => {
    let text = "";
    const timer = setTimeout(() => reject(new Error("browser did not start (no DevTools address in 20 s)")), 20000);
    child.stderr.on("data", (chunk) => {
      text += chunk;
      const match = /DevTools listening on (ws:\/\/\S+)/.exec(text);
      if (match) { clearTimeout(timer); resolve({ child, url: match[1] }); }
    });
    child.on("exit", (code) => reject(new Error(`browser exited (${code}): ${text.slice(-400)}`)));
  });
}

function connect(url) {
  const socket = new WebSocket(url);
  let next = 0;
  const waiting = new Map();
  socket.addEventListener("message", (event) => {
    const message = JSON.parse(event.data);
    const pending = waiting.get(message.id);
    if (!pending) return;
    waiting.delete(message.id);
    if (message.error) pending.reject(new Error(message.error.message));
    else pending.resolve(message.result);
  });
  const send = (method, params = {}, sessionId) => new Promise((resolve, reject) => {
    const id = ++next;
    waiting.set(id, { resolve, reject });
    socket.send(JSON.stringify({ id, method, params, ...(sessionId ? { sessionId } : {}) }));
  });
  return new Promise((resolve, reject) => {
    socket.addEventListener("open", () => resolve({ send, close: () => socket.close() }));
    socket.addEventListener("error", () => reject(new Error(`cannot connect to ${url}`)));
  });
}

// Runs in the page. Returns the problems found, one per element kind (tag + classes) to keep the report short.
function detect() {
  const problems = [];
  const root = document.documentElement;
  if (root.scrollWidth > root.clientWidth + 1) problems.push({ kind: "scroll-x", where: "page", by: root.scrollWidth - root.clientWidth });
  const name = (el) => `${el.tagName.toLowerCase()}${typeof el.className === "string" && el.className.trim() ? "." + el.className.trim().split(/\s+/).join(".") : ""}`;
  const text = (el) => (el.textContent || "").replace(/\s+/g, " ").trim().slice(0, 60);
  for (const el of document.querySelectorAll("body *")) {
    if (el.closest("svg, canvas, .react-flow, [data-ui-check=skip]")) continue;
    const style = getComputedStyle(el);
    if (style.display === "none" || style.visibility === "hidden" || style.position === "fixed" || style.position === "absolute") continue;
    const box = el.getBoundingClientRect();
    if (!box.width || !box.height) continue;
    if (box.right < 0 || box.left > root.clientWidth) continue;
    const ellipsis = style.textOverflow === "ellipsis";
    const parent = el.parentElement;
    if (parent && !ellipsis) {
      const parentStyle = getComputedStyle(parent);
      const scrolls = /(auto|scroll)/.test(parentStyle.overflowX);
      const allowed = Math.max(0, -parseFloat(style.marginRight) || 0) + 2;
      const edge = parent.getBoundingClientRect().right - (parseFloat(parentStyle.borderRightWidth) || 0);
      if (!scrolls && box.right > edge + allowed) problems.push({ kind: "sticks-out", where: name(el), in: name(parent), by: Math.round(box.right - edge), text: text(el) });
    }
    const clips = /(hidden|clip)/.test(style.overflowX);
    if (clips && !ellipsis && el.scrollWidth > el.clientWidth + 1 && el.childNodes.length && style.whiteSpace !== "nowrap"
      && [...el.childNodes].some((node) => node.nodeType === 3 && node.textContent.trim())) {
      problems.push({ kind: "cut", where: name(el), by: el.scrollWidth - el.clientWidth, text: text(el) });
    }
    if (/(auto|scroll)/.test(style.overflowX) && /(auto|scroll)/.test(style.overflowY) && el.scrollWidth > el.clientWidth + 1
      && !el.matches("pre, code, table, .md-table-wrap, [class*=table]")) {
      problems.push({ kind: "scroll-x", where: name(el), by: el.scrollWidth - el.clientWidth, text: text(el) });
    }
  }
  const seen = new Set();
  return problems.filter((problem) => {
    const key = `${problem.kind}|${problem.where}`;
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

const READY = `document.readyState === "complete" && !document.querySelector(".md-loading")
  && (document.getElementById("app")?.children.length || 0) > 0`;

async function settle(send, session, ms = 15000) {
  const end = Date.now() + ms;
  while (Date.now() < end) {
    const { result } = await send("Runtime.evaluate", { expression: READY, returnByValue: true }, session);
    if (result.value) break;
    await new Promise((resolve) => setTimeout(resolve, 200));
  }
  await new Promise((resolve) => setTimeout(resolve, 700)); // web components upgrade, graphs fit, fonts swap
}

const binary = findBrowser();
if (!binary) {
  console.error("Không thấy Chrome / Edge. Đặt biến VIEWER_HUB_CHROME tới file chạy của trình duyệt.");
  process.exit(2);
}
const profile = mkdtempSync(join(tmpdir(), "viewer-hub-ui-check-"));
const { child, url } = await launch(binary, profile);
const report = [];
try {
  const { send, close } = await connect(url);
  const { targetId } = await send("Target.createTarget", { url: "about:blank" });
  const { sessionId: session } = await send("Target.attachToTarget", { targetId, flatten: true });
  await send("Page.enable", {}, session);
  for (const width of config.widths) {
    await send("Emulation.setDeviceMetricsOverride", { width, height: HEIGHT, deviceScaleFactor: 1, mobile: false }, session);
    for (const page of config.pages) {
      await send("Page.navigate", { url: "about:blank" }, session);
      await send("Page.navigate", { url: config.base + page.url }, session);
      await settle(send, session);
      if (page.click) {
        await send("Runtime.evaluate", { expression: `document.querySelector(${JSON.stringify(page.click)})?.click()` }, session);
        await settle(send, session, 5000);
      }
      const { result, exceptionDetails } = await send("Runtime.evaluate", { expression: `(${detect})()`, returnByValue: true }, session);
      const problems = exceptionDetails ? [{ kind: "error", where: exceptionDetails.text }] : result.value;
      const shot = await send("Page.captureScreenshot", { format: "png" }, session);
      const file = `${page.name}-${width}.png`;
      writeFileSync(join(config.out, file), Buffer.from(shot.data, "base64"));
      report.push({ page: page.name, url: page.url, width, screenshot: file, problems });
      const mark = problems.length ? "✗" : "✓";
      console.log(`${mark} ${String(width).padStart(4)}px  ${page.name}${problems.length ? `: ${problems.length} vấn đề` : ""}`);
      for (const problem of problems) {
        console.log(`      ${problem.kind.padEnd(10)} ${problem.where}${problem.in ? ` trong ${problem.in}` : ""}${problem.by ? ` (+${problem.by}px)` : ""}${problem.text ? `  «${problem.text}»` : ""}`);
      }
    }
  }
  close();
} finally {
  child.kill();
  setTimeout(() => rmSync(profile, { recursive: true, force: true }), 500);
}
writeFileSync(join(config.out, "report.json"), JSON.stringify(report, null, 2));
const failed = report.filter((entry) => entry.problems.length).length;
console.log(failed ? `\n${failed}/${report.length} trang có chữ tràn khung. Ảnh và report.json: ${config.out}`
  : `\nOK: ${report.length} trang × cỡ màn hình, không có gì tràn khung. Ảnh: ${config.out}`);
process.exitCode = failed ? 1 : 0;
