// Viewer Hub addon SDK: build, check and zip the addon in this folder (AGENTS.md §2, §8).
//
//   npm run build                 src/main.mjs → main.mjs (Node code using npm packages), web/index.jsx → ui/ui.js
//   npm run watch [-- --out DIR]  rebuild the page on save (DIR: the installed addon's ui/, then F5 in the browser)
//   npm run check                 the checks Viewer Hub runs at install: addon.json, files, GUIDE.md, security rules
//   npm run test                  the addon's tests in test/ (Python: unittest with this Hub's SDK; Node: node --test)
//   npm run zip                   build + check + dist/<id>-<version>.zip, ready to upload
//   npm run exports [-- URL]      what the addons on a running Viewer Hub let others read → .sdk/addons/<id>.json/.md
//                                 (URL: http://127.0.0.1:<port>, default $VIEWER_HUB_URL or http://127.0.0.1:8700)
//
// build / zip also write uses.<id>.built in addon.json: the contract of each used addon (.sdk/addons/<id>.json) this
// addon is built against, which Viewer Hub compares with the installed one (an update that breaks it is caught).
//
// The project folder IS the addon: the files below are development files, never installed (Viewer Hub skips them,
// and the zip leaves them out), so zipping the folder by hand works too.
import { spawnSync } from "node:child_process";
import { createHash } from "node:crypto";
import { existsSync, mkdirSync, readFileSync, readdirSync, statSync, writeFileSync } from "node:fs";
import { dirname, join, relative, resolve, sep } from "node:path";
import { fileURLToPath } from "node:url";
import { deflateRawSync } from "node:zlib";

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");
// Same lists as viewer_hub/addons/install.py DEV_ROOT / DEV_ANY.
export const DEV_ROOT = ["web", "src", "test", "tests", "dist", "node_modules", "AGENTS.md", "CLAUDE.md", "README.md",
  "package.json", "package-lock.json"];
export const DEV_ANY = ["node_modules", "__pycache__", "__MACOSX"];
// React, the JSX runtime and the Hub's kit are NOT bundled: the browser imports them from the Hub serving the page.
const SDK = {
  react: "react",
  "react/jsx-runtime": "jsx-runtime",
  "react-dom": "react-dom",
  "@vh/md": "md",
  "@vh/ui": "ui",
  "@vh/mermaid": "mermaid",
  "@vh/flow": "flow",
};

const ID_RE = /^[a-z][a-z0-9-]{1,40}$/;
// Ids the Hub keeps for itself (builtin modules, its own pages: viewer_hub/addons/install.py reserved_ids).
export const RESERVED = ["codemap", "fsearch", "csv", "docs", "monitor", "premium", "settings", "help", "api", "sdk", "static", "x",
  "call", "staged", "contracts"];
export const MCP_TAKEN = ["codemap", "search", "csv", "monitor"]; // viewer-hub mcp <command> of builtin modules
// The security rules of viewer_hub/core/scan.py (tests/test_addon_sdk.py runs both on the same samples).
const EXECUTABLE = [".pyd", ".so", ".dll", ".exe", ".node", ".dylib", ".ps1", ".bat", ".cmd", ".vbs", ".sh", ".com",
  ".scr", ".msi", ".jar"];
const PY_ERRORS = [
  [/shell\s*=\s*True/gi, "subprocess với shell=True"],
  [/\bos\.system\(|\bos\.popen\(/gi, "os.system / os.popen"],
  [/\b(eval|exec)\(/gi, "eval / exec"],
  [/powershell|cmd(\.exe)?\s*\/c/gi, "gọi PowerShell / cmd /c"],
  [/winreg|HKEY_|CurrentVersion\\\\Run/gi, "registry / autostart"],
  [/pickle\.loads?|marshal\.loads?/gi, "giải tuần tự không an toàn"],
  [/yaml\.load\((?!.*Loader=_SafeLoader)/gi, "yaml.load không có SafeLoader"],
];
const PY_NOTES = [
  [/\b(urllib\.request|requests|httpx|http\.client|socket\.create_connection)\b/gi, "gọi mạng"],
  [/\bsubprocess\b/gi, "chạy tiến trình"],
  [/\bsocket\.socket\(|\\\\\.\\pipe/gi, "socket / named pipe"],
  [/base64\.b64decode/gi, "payload base64"],
];
const WEB_ERRORS = [
  [/https?:\/\/(fonts\.googleapis|fonts\.gstatic|cdn\.|unpkg|jsdelivr|cdnjs)/g, "tải từ CDN"],
  [/\beval\(|new Function\(/g, "eval trong JS"],
  [/innerHTML\s*=/g, "innerHTML (dùng textContent)"],
];
// The page redraws what the Hub draws above it (AGENTS.md "Hub vẽ sẵn"). Same as UI_RULES in core/scan.py.
const HUB_DRAWS = "Hub đã vẽ sẵn phần đầu trang addon (trạng thái, Cài đặt, Nhật ký, chạy / dừng) và banner khi thiếu "
  + "setting: khai báo `settings` (kèm `required`) trong addon.json, mở hộp Cài đặt bằng useAddon().openSettings()";
const UI_ERRORS = [
  [/\/api\/addons\b/giu, `trang addon gọi API quản lý addon của Hub. ${HUB_DRAWS}`],
  [/["'`]\/(settings?|config|configuration)(?:["'`/?])/giu, `trang addon tự đọc / ghi cấu hình qua API riêng. ${HUB_DRAWS}`],
  [/["'`>]\s*(Cài đặt|Mở cài đặt|Lưu cài đặt|Nhật ký|Xem nhật ký|Xem log|Khởi động lại)\s*["'`<]/giu,
    `nút / nhãn trùng phần đầu trang của Hub. ${HUB_DRAWS}`],
  [/md-banner(?:(?!md-banner)[\s\S]){0,600}?(cấu hình|cài đặt|thiết lập|chưa nhập|chưa chọn|chưa điền)/giu,
    `banner tự làm về cấu hình. ${HUB_DRAWS}`],
];
const decodeEscapes = (text) => text.replace(/\\u\{([0-9a-fA-F]+)\}|\\u([0-9a-fA-F]{4})|\\x([0-9a-fA-F]{2})/g,
  (_, a, b, c) => String.fromCodePoint(parseInt(a || b || c, 16)));

/** UI_ERRORS in one page file: the bundle (ui/*.js) or its source (web/*.jsx). */
export function scanUi(rel, text) {
  const decoded = decodeEscapes(text);
  return UI_ERRORS.flatMap(([pattern, message]) => [...new Set(matches(decoded, pattern))].map((line) => `${rel}:${line}: ${message}`));
}
const NODE_ERRORS = [[/shell\s*:\s*true/gi, "child_process với shell: true"]];
const NODE_NOTES = [
  [/\bchild_process\b/g, "chạy tiến trình (child_process)"],
  [/\beval\(|new Function\(/g, "eval trong JS"],
  [/powershell|cmd(\.exe)?\s*\/c/g, "nhắc tới PowerShell / cmd"],
];
const WINDOWS_DEVICE = /^(con|prn|aux|nul|com[0-9]|lpt[0-9])(\..*)?$/i;
const WINDOWS_BAD = /[<>"|?*\x00-\x1f]/;
const VERSION_RE = /^\d+\.\d+\.\d+([.-][0-9A-Za-z.-]+)?$/;

export function isDev(rel) {
  const parts = rel.split("/");
  return DEV_ROOT.includes(parts[0]) || parts.some((p) => DEV_ANY.includes(p) || p.startsWith(".")) || rel.endsWith(".pyc");
}

function fail(message) {
  console.error(`✗ ${message}`);
  process.exit(1);
}

function manifest() {
  const file = join(ROOT, "addon.json");
  if (!existsSync(file)) fail("chưa có addon.json: tạo addon bằng  npm run new -- simple <id>  (hoặc daemon)");
  try {
    return JSON.parse(readFileSync(file, "utf8"));
  } catch (error) {
    return fail(`addon.json không phải JSON hợp lệ: ${error.message}`);
  }
}

async function buildCode() {
  const source = join(ROOT, "src", "main.mjs");
  if (!existsSync(source)) return;
  const { build } = await import("esbuild");
  await build({
    entryPoints: [source],
    outfile: join(ROOT, "main.mjs"),
    bundle: true,
    platform: "node",
    format: "esm",
    target: "node20",
    // Minify the shipped bundle: one file, mangled names, no comments — the src/ stays for development but is never
    // installed (isDev), so the source does not travel with the addon. legalComments keeps bundled packages' licenses.
    minify: true,
    legalComments: "eof",
    // CommonJS packages bundled into an ES module still call require() for Node built-ins.
    banner: { js: "import { createRequire as __vhRequire } from 'node:module'; const require = __vhRequire(import.meta.url);" },
    logLevel: "warning",
  });
  console.log("✓ src/main.mjs → main.mjs (bundle minified)");
}

async function buildUi({ watch = false, out } = {}) {
  const entry = join(ROOT, "web", "index.jsx");
  if (!existsSync(entry)) return;
  const { build } = await import("vite");
  const { default: react } = await import("@vitejs/plugin-react");
  const sdk = {
    name: "viewer-hub-sdk",
    enforce: "pre",
    resolveId(id) {
      return SDK[id] ? { id: `/static/dist/sdk/${SDK[id]}.js`, external: true } : null;
    },
  };
  const outDir = out ? resolve(out) : join(ROOT, "ui");
  await build({
    configFile: false,
    root: join(ROOT, "web"),
    logLevel: "warn",
    plugins: [sdk, react()],
    define: { "process.env.NODE_ENV": '"production"' },
    build: {
      outDir,
      emptyOutDir: true,
      sourcemap: false,
      minify: true,
      assetsInlineLimit: 0,
      watch: watch ? {} : null,
      lib: { entry, formats: ["es"], fileName: () => "ui.js", cssFileName: "ui" },
      rollupOptions: {
        output: {
          chunkFileNames: "chunks/[name]-[hash].js",
          assetFileNames: (assetInfo) => (assetInfo.name && assetInfo.name.endsWith(".css")) ? "ui.css" : "assets/[name]-[hash][extname]",
        },
      },
    },
  });
  console.log(`✓ web/index.jsx → ${relative(ROOT, outDir) || outDir}${watch ? " (đang theo dõi, Ctrl+C để dừng)" : ""}`);
}

function contractOf(id) {
  const file = join(ROOT, ".sdk", "addons", `${id}.json`);
  if (!existsSync(file)) return null;
  try {
    return JSON.parse(readFileSync(file, "utf8"));
  } catch {
    return null;
  }
}

/** uses.<id>.built from .sdk/addons/<id>.json (addon.json is rewritten only when it changes). */
function fillBuilt(data) {
  if (!data.uses || typeof data.uses !== "object") return data;
  let changed = false;
  for (const [id, use] of Object.entries(data.uses)) {
    const contract = contractOf(id);
    if (!contract) {
      console.log(`! chưa có contract của ${id} (.sdk/addons/${id}.json): npm run exports khi Viewer Hub đang chạy có ${id}; `
        + "built để trống, Viewer Hub chỉ kiểm được version và tên export");
      continue;
    }
    const byName = Object.fromEntries((contract.exports ?? []).map((e) => [e.name, e]));
    const missing = (use.exports ?? []).filter((name) => !byName[name]);
    if (missing.length) fail(`uses.${id}: ${id} ${contract.version} không có export ${missing.join(", ")} (.sdk/addons/${id}.md)`);
    const built = { version: contract.version, contract: Object.fromEntries((use.exports ?? []).map((name) =>
      [name, { params: byName[name].params ?? { type: "object" }, returns: byName[name].returns }])) };
    if (JSON.stringify(use.built) !== JSON.stringify(built)) {
      use.built = built;
      changed = true;
    }
  }
  if (changed) {
    writeFileSync(join(ROOT, "addon.json"), JSON.stringify(data, null, 2) + "\n");
    console.log("✓ addon.json: uses.*.built theo .sdk/addons/");
  }
  return data;
}

/** The shape of exports / uses (Viewer Hub checks the schemas themselves and the compatibility at install). */
function checkSharing(data, problems) {
  const sharing = ["exports", "uses", "requires"].filter((key) => data[key] != null);
  if (sharing.length && data.schemaVersion !== 2) problems.push(`${sharing.join(", ")} cần "schemaVersion": 2`);
  const names = new Set();
  for (const [index, e] of (Array.isArray(data.exports) ? data.exports : []).entries()) {
    const where = `exports[${index}]${e?.name ? ` (${e.name})` : ""}`;
    if (!/^[a-z0-9_]{1,64}$/.test(e?.name ?? "")) problems.push(`${where}: name chữ thường, số, _`);
    if (names.has(e?.name)) problems.push(`${where}: trùng tên`);
    names.add(e?.name);
    if (!e?.description) problems.push(`${where}: thiếu description`);
    if (e?.returns?.type !== "object") problems.push(`${where}: returns phải là schema type object`);
    if (e?.params && e.params.type !== "object") problems.push(`${where}: params phải là schema type object`);
    if (!("example" in (e ?? {}))) problems.push(`${where}: thiếu example (kết quả mẫu đúng returns)`);
  }
  if (data.exports != null && !Array.isArray(data.exports)) problems.push("exports phải là danh sách");
  for (const [id, use] of Object.entries(data.uses ?? {})) {
    if (id === data.id) problems.push("uses: addon không dùng chính nó");
    if (!ID_RE.test(id)) problems.push(`uses.${id}: id addon không hợp lệ`);
    if (typeof use?.version !== "string" || !use.version.trim()) problems.push(`uses.${id}.version: khoảng version (vd. ^1.2.0)`);
    if (!Array.isArray(use?.exports) || !use.exports.length) problems.push(`uses.${id}.exports: tên export dùng tới`);
  }
  if (data.exports?.length && data.runtime === "python" && existsSync(join(ROOT, "main.py"))) {
    const code = readFileSync(join(ROOT, "main.py"), "utf8");
    const missing = data.exports.filter((e) => !code.includes(`"${e.name}"`) && !code.includes(`'${e.name}'`));
    if (missing.length) problems.push(`main.py chưa có @addon.export cho ${missing.map((e) => e.name).join(", ")}`);
  }
}

/** .sdk/addons/<id>.json and .md from a running Viewer Hub (GET /api/addons/contracts). */
async function fetchExports(url) {
  const base = (url || process.env.VIEWER_HUB_URL || "http://127.0.0.1:8700").replace(/\/+$/, "");
  let reply;
  try {
    const response = await fetch(`${base}/api/addons/contracts`);
    if (!response.ok) fail(`${base}: trả lỗi ${response.status} (Viewer Hub cũ chưa có /api/addons/contracts?)`);
    reply = await response.json();
  } catch (error) {
    fail(`không kết nối được ${base}: mở Viewer Hub (hoặc npm run exports -- http://127.0.0.1:<cổng>) (${error.message})`);
  }
  const dir = join(ROOT, ".sdk", "addons");
  mkdirSync(dir, { recursive: true });
  for (const item of reply.addons ?? []) {
    if (!ID_RE.test(item.id ?? "")) continue;
    writeFileSync(join(dir, `${item.id}.json`), JSON.stringify(item, null, 2) + "\n");
    writeFileSync(join(dir, `${item.id}.md`), markdown(item));
    console.log(`✓ .sdk/addons/${item.id}.json, .md  (${item.version}: ${(item.exports ?? []).map((e) => e.name).join(", ")})`);
  }
  if (!(reply.addons ?? []).length) console.log("Không addon nào trên Viewer Hub này có exports");
}

// Same text as viewer_hub/addons/sdk_kit.py contract_markdown (the kit downloaded from the Hub has these already).
function markdown(item) {
  const names = item.exports.map((e) => e.name);
  const lines = [`# ${item.name} (\`${item.id}\` ${item.version}): dữ liệu cho addon khác`, "", item.summary ?? "", "",
    "Khai trong addon.json (`schemaVersion` 2), chỉ giữ export cần dùng; `npm run build` tự điền `built`:", "",
    "```json", JSON.stringify({ uses: { [item.id]: { version: `^${item.version.split("-")[0]}`, exports: names } } }, null, 2),
    "```", "",
    `Gọi: Python \`addon.call("${item.id}", "<export>", {...})\`, Node \`await hub.call("${item.id}", "<export>", {...})\` `
      + "(AGENTS.md, mục Dùng dữ liệu addon khác).", ""];
  for (const e of item.exports) {
    lines.push(`## \`${e.name}\``, "", e.description, "");
    const props = e.params?.properties ?? {};
    const required = new Set(e.params?.required ?? []);
    if (Object.keys(props).length) {
      lines.push("| Tham số | Kiểu | Bắt buộc | Ghi chú |", "|---|---|---|---|");
      for (const [name, schema] of Object.entries(props)) {
        let note = schema.description ?? "";
        if ("default" in schema) note += ` (mặc định \`${JSON.stringify(schema.default)}\`)`;
        if (schema.enum) note += ` (một trong ${schema.enum.map((v) => `\`${v}\``).join(", ")})`;
        lines.push(`| \`${name}\` | ${schema.type} | ${required.has(name) ? "có" : ""} | ${note.trim()} |`);
      }
      lines.push("");
    } else lines.push("Không có tham số.", "");
    lines.push("Kết quả (schema `returns`; có thể có thêm trường mới, bỏ qua trường lạ):", "", "```json",
      JSON.stringify(e.returns, null, 2), "```", "", "Ví dụ:", "", "```json", JSON.stringify(e.example, null, 2), "```", "");
  }
  return lines.join("\n");
}

/** What Viewer Hub checks at install: addon.json, files, GUIDE.md, the security rules (scan). The Hub checks again. */
function check(data) {
  const problems = [];
  checkSharing(data, problems);
  if (!ID_RE.test(data.id ?? "")) problems.push("id: chữ thường, số, '-' (vd. jira-reader)");
  if (!VERSION_RE.test(data.version ?? "")) problems.push("version: dạng 1.2.3");
  if (!["managed", "daemon", "external"].includes(data.lifecycle)) problems.push("lifecycle: managed, daemon hoặc external");
  const external = data.lifecycle === "external";
  if (external) {
    const port = data.service?.port;
    if (!Number.isInteger(port) || port < 1024 || port > 65535) problems.push('external: "service": {"port": 1024-65535}');
    if (data.runtime || data.entry) problems.push("external: bỏ runtime / entry (chương trình do người dùng tự chạy)");
  } else if (!["python", "node"].includes(data.runtime)) problems.push("runtime: python hoặc node");
  const entry = data.entry ?? "";
  if (external) {
    // nothing to run: the user's own program serves /health, /api/*, /mcp on 127.0.0.1
  } else if (entry !== (data.runtime === "node" ? "main.mjs" : "main.py")) {
    problems.push(`entry: luôn là ${data.runtime === "node" ? "main.mjs" : "main.py"} ở gốc thư mục (SDK)`);
  } else if (!existsSync(join(ROOT, entry))) {
    problems.push(`thiếu ${entry}${data.runtime === "node" && existsSync(join(ROOT, "src")) ? " (npm run build)" : ""}`);
  }
  const label = data.menu?.label ?? "";
  if (!label) problems.push("menu.label: tên trên menu");
  const guide = existsSync(join(ROOT, "GUIDE.md")) ? readFileSync(join(ROOT, "GUIDE.md"), "utf8") : null;
  if (guide === null) problems.push("thiếu GUIDE.md");
  else if (!guide.startsWith(`## ${label}`)) problems.push(`GUIDE.md phải bắt đầu bằng "## ${label}"`);
  if (guide !== null && data.mcp?.tools?.length) {
    const table = /^### Tool cho AI\n([\s\S]*?)(?=^#{2,3} |(?![\s\S]))/m.exec(guide);
    const documented = new Set([...(table?.[1] ?? "").matchAll(/^\| `([a-z0-9_]+)` \|/gm)].map((m) => m[1]));
    const missing = data.mcp.tools.filter((tool) => !documented.has(tool));
    if (missing.length) problems.push(`GUIDE.md: thiếu dòng cho tool ${missing.join(", ")} trong "### Tool cho AI"`);
  }
  for (const key of ["script", "style"]) {
    const file = data.ui?.[key];
    if (file && !existsSync(join(ROOT, file))) problems.push(`thiếu ${file} (npm run build)`);
  }
  if (existsSync(join(ROOT, "web", "index.jsx")) && !data.ui?.script) problems.push('có web/index.jsx nhưng addon.json thiếu "ui": {"script": "ui/ui.js"}');
  if (existsSync(join(ROOT, "web")) && data.ui?.script && existsSync(join(ROOT, data.ui.script))) {
    const newest = Math.max(...files(join(ROOT, "web")).map((f) => statSync(f).mtimeMs));
    if (newest > statSync(join(ROOT, data.ui.script)).mtimeMs) problems.push(`${data.ui.script} cũ hơn web/: chạy npm run build`);
  }
  if (RESERVED.includes(data.id)) problems.push(`id ${data.id} là mục có sẵn của Viewer Hub: đổi id`);
  if (MCP_TAKEN.includes(data.mcp?.command)) problems.push(`mcp.command ${data.mcp.command} là lệnh có sẵn của Viewer Hub`);
  const { errors, notes } = scan();
  if (existsSync(join(ROOT, "web"))) {
    const source = files(join(ROOT, "web")).filter((f) => /\.(jsx?|tsx?|mjs)$/.test(f))
      .flatMap((f) => scanUi(relative(ROOT, f).split(sep).join("/"), readFileSync(f, "utf8")));
    // Name the source lines; the same problem in the bundle would only repeat them.
    problems.push(...source, ...(source.length ? errors.filter((e) => !e.startsWith("ui/") || !UI_ERRORS.some(([, m]) => e.endsWith(m))) : errors));
  } else problems.push(...errors);
  if (problems.length) fail(`addon chưa đúng:\n  - ${problems.join("\n  - ")}`);
  for (const note of notes) console.log(`! lưu ý (admin sẽ thấy khi cài): ${note}`);
  console.log(`✓ ${data.id} ${data.version}: addon.json, ${external ? `127.0.0.1:${data.service.port}` : data.entry}, GUIDE.md`);
}

function matches(text, pattern) {
  const lines = text.split("\n");
  const out = [];
  for (const match of text.matchAll(pattern)) {
    const line = text.slice(0, match.index).split("\n").length;
    if (!(lines[line - 1] ?? "").includes("noqa: security")) out.push(line);
  }
  return out;
}

/** What Viewer Hub refuses (errors) or shows the admin (notes) in the files it would install. */
export function scan(root = ROOT) {
  const errors = [];
  const notes = [];
  const seen = new Map();
  const installed = files(root).map((f) => relative(root, f).split(sep).join("/")).filter((rel) => !isDev(rel)).sort();
  for (const rel of installed) {
    for (const part of rel.split("/")) {
      if (WINDOWS_DEVICE.test(part) || WINDOWS_BAD.test(part) || /[. ]$/.test(part)) errors.push(`${rel}: tên file không dùng được trên Windows`);
    }
    const folded = rel.toLowerCase();
    if (seen.has(folded)) errors.push(`${seen.get(folded)}, ${rel}: hai file chỉ khác chữ hoa / thường (Windows coi là một)`);
    seen.set(folded, rel);
    const suffix = rel.includes(".") ? rel.slice(rel.lastIndexOf(".")).toLowerCase() : "";
    if (EXECUTABLE.includes(suffix) && rel !== "node/node.exe") {
      errors.push(`${rel}: file thực thi / native`);
      continue;
    }
    if (![".py", ".js", ".mjs", ".cjs", ".css", ".html"].includes(suffix)) continue;
    const text = readFileSync(join(root, rel), "utf8");
    const add = (list, rules, once = false) => {
      for (const [pattern, message] of rules) {
        const lines = matches(text, pattern);
        if (once && lines.length) list.push(`${rel}: ${message}`);
        else if (!once) list.push(...lines.map((line) => `${rel}:${line}: ${message}`));
      }
    };
    if (suffix === ".py") {
      add(errors, PY_ERRORS);
      add(notes, PY_NOTES);
    } else if (rel.startsWith("ui/") || suffix === ".css" || suffix === ".html") {
      add(errors, WEB_ERRORS);
      if (suffix === ".js" || suffix === ".mjs") errors.push(...scanUi(rel, text));
    } else {
      add(errors, NODE_ERRORS);
      add(notes, NODE_NOTES, true);
    }
  }
  return { errors, notes };
}

function files(dir) {
  // node_modules/, .git/… are never installed: not walked at all
  return readdirSync(dir, { withFileTypes: true }).flatMap((e) => (!e.isDirectory() ? [join(dir, e.name)]
    : DEV_ANY.includes(e.name) || e.name.startsWith(".") ? [] : files(join(dir, e.name))));
}

// ── zip (store / deflate, no dependency) ─────────────────────────────────────────────────────────────────────
const CRC = new Uint32Array(256).map((_, n) => {
  let c = n;
  for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
  return c >>> 0;
});
function crc32(buffer) {
  let c = 0xffffffff;
  for (const byte of buffer) c = CRC[(c ^ byte) & 0xff] ^ (c >>> 8);
  return (c ^ 0xffffffff) >>> 0;
}

const DOS_DATE = (1 << 5) | 1; // 1980-01-01, a fixed valid date: the same addon always zips to the same bytes

function writeZip(target, entries) {
  const chunks = [];
  const central = [];
  let offset = 0;
  for (const { name, data } of entries) {
    const packed = deflateRawSync(data);
    const method = packed.length < data.length ? 8 : 0;
    const body = method ? packed : data;
    const nameBytes = Buffer.from(name, "utf8");
    const crc = crc32(data);
    const local = Buffer.alloc(30);
    local.writeUInt32LE(0x04034b50, 0); local.writeUInt16LE(20, 4); local.writeUInt16LE(0x0800, 6);
    local.writeUInt16LE(method, 8); local.writeUInt16LE(0, 10); local.writeUInt16LE(DOS_DATE, 12); local.writeUInt32LE(crc, 14);
    local.writeUInt32LE(body.length, 18); local.writeUInt32LE(data.length, 22); local.writeUInt16LE(nameBytes.length, 26);
    chunks.push(local, nameBytes, body);
    const head = Buffer.alloc(46);
    head.writeUInt32LE(0x02014b50, 0); head.writeUInt16LE(20, 4); head.writeUInt16LE(20, 6); head.writeUInt16LE(0x0800, 8);
    head.writeUInt16LE(method, 10); head.writeUInt16LE(0, 12); head.writeUInt16LE(DOS_DATE, 14); head.writeUInt32LE(crc, 16); head.writeUInt32LE(body.length, 20);
    head.writeUInt32LE(data.length, 24); head.writeUInt16LE(nameBytes.length, 28); head.writeUInt32LE(offset, 42);
    central.push(head, nameBytes);
    offset += 30 + nameBytes.length + body.length;
  }
  const size = central.reduce((n, b) => n + b.length, 0);
  const end = Buffer.alloc(22);
  end.writeUInt32LE(0x06054b50, 0); end.writeUInt16LE(entries.length, 8); end.writeUInt16LE(entries.length, 10);
  end.writeUInt32LE(size, 12); end.writeUInt32LE(offset, 16);
  mkdirSync(dirname(target), { recursive: true });
  writeFileSync(target, Buffer.concat([...chunks, ...central, end]));
}

function zip(data) {
  const kept = files(ROOT).map((f) => relative(ROOT, f).split(sep).join("/")).filter((rel) => !isDev(rel)).sort();
  const target = join(ROOT, "dist", `${data.id}-${data.version}.zip`);
  writeZip(target, kept.map((rel) => ({ name: `${data.id}/${rel}`, data: readFileSync(join(ROOT, rel)) })));
  const digest = createHash("sha256").update(readFileSync(target)).digest("hex").slice(0, 12);
  console.log(`✓ ${relative(ROOT, target)}  (${kept.length} file, sha256 ${digest}…)\n  Viewer Hub → Cài đặt → Addon → Cài addon (.zip)`);
}

// addon.call() answers from .sdk/addons/<id>.json (or fake()) in tests: never a real Hub.
const TEST_ENV = { VIEWER_HUB_ADDON_FOLDER: ROOT, VIEWER_HUB_URL: "", VIEWER_HUB_CALLER_TOKEN: "",
  VIEWER_HUB_NODE_SDK: join(ROOT, ".sdk", "node", "hub_client.mjs") };

/** test/ (or tests/): Python with .sdk/python (the Hub's real SDK) and lib/ on the path, so `from viewer_hub.addons.sdk
 * import Addon` works without a Hub; Node with node --test. */
function test(data) {
  const dir = ["test", "tests"].find((name) => existsSync(join(ROOT, name)));
  if (!dir) fail("chưa có thư mục test/ (AGENTS.md §8)");
  let result;
  if (data.runtime === "python") {
    const env = { ...process.env, PYTHONPATH: [join(ROOT, ".sdk", "python"), join(ROOT, "lib"), ROOT].join(process.platform === "win32" ? ";" : ":"),
      PYTHONDONTWRITEBYTECODE: "1", ...TEST_ENV };
    const python = [process.env.VIEWER_HUB_PYTHON, "python3", "python", "py"].filter(Boolean)
      .find((name) => spawnSync(name, ["--version"], { stdio: "ignore" }).status === 0);
    if (!python) fail("không tìm thấy Python 3 (đặt VIEWER_HUB_PYTHON=<đường dẫn python>)");
    result = spawnSync(python, ["-m", "unittest", "discover", "-s", dir], { cwd: ROOT, env, stdio: "inherit" });
  } else {
    // the files themselves: Node 22 reads a directory argument as a file name
    const tests = files(join(ROOT, dir)).filter((f) => /(\.test\.[cm]?js|^test.*\.[cm]?js)$/.test(f.split(sep).pop()))
      .map((f) => relative(ROOT, f));
    if (!tests.length) fail(`không có file *.test.mjs trong ${dir}/`);
    result = spawnSync(process.execPath, ["--test", ...tests], { cwd: ROOT, stdio: "inherit", env: { ...process.env, ...TEST_ENV } });
  }
  process.exit(result.status ?? 1);
}

if (process.argv[1] && fileURLToPath(import.meta.url) === resolve(process.argv[1])) {
  const args = process.argv.slice(2);
  const command = args[0] ?? "build";
  const data = manifest();
  if (command === "watch") {
    const at = args.indexOf("--out");
    await buildUi({ watch: true, out: at >= 0 ? args[at + 1] : undefined });
  } else if (command === "check") {
    check(data);
  } else if (command === "test") {
    test(data);
  } else if (command === "exports") {
    await fetchExports(args[1]);
  } else if (command === "build" || command === "zip") {
    await buildCode();
    await buildUi();
    fillBuilt(data);
    check(data);
    if (command === "zip") zip(data);
  } else {
    fail(`không biết lệnh ${command}: build | watch | check | test | zip | exports`);
  }
}
