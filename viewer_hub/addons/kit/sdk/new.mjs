// Starts the addon in this folder from a template:   npm run new -- simple|daemon|external <id>
//
//   simple   managed, Python: API for the page + MCP tools for AI (most addons)
//   daemon   daemon, Node: a long-running program Viewer Hub starts / stops (lives on when the Hub closes)
//   external a program in any language (.NET, Java…) the user runs; Viewer Hub only connects to it on 127.0.0.1
//
// Writes addon/addon.json, addon/GUIDE.md, src/main.py | src/main.mjs (none for external), web/index.jsx here (the
// layout of AGENTS.md §2); never overwrites an existing addon.
import { cpSync, existsSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const ROOT = resolve(HERE, "..");
const [kind, id] = process.argv.slice(2);
const TEMPLATES = { simple: "simple", daemon: "daemon", external: "external" };

if (!TEMPLATES[kind] || !/^[a-z][a-z0-9-]{1,40}$/.test(id ?? "")) {
  console.error("Cách dùng: npm run new -- simple|daemon|external <id>\n  id: chữ thường, số, '-' (vd. jira-reader)");
  process.exit(2);
}
if (existsSync(join(ROOT, "addon", "addon.json"))) {
  console.error("Thư mục này đã có addon/addon.json: mỗi thư mục là một addon. Giải nén SDK ra thư mục khác cho addon mới.");
  process.exit(1);
}
cpSync(join(HERE, "templates", TEMPLATES[kind]), ROOT, { recursive: true });
const file = join(ROOT, "addon", "addon.json");
const data = JSON.parse(readFileSync(file, "utf8"));
data.id = id;
writeFileSync(file, JSON.stringify(data, null, 2) + "\n");
const pkg = join(ROOT, "package.json");
const npm = JSON.parse(readFileSync(pkg, "utf8"));
npm.name = id;
writeFileSync(pkg, JSON.stringify(npm, null, 2) + "\n");
console.log(`✓ addon ${id} (${kind}): sửa addon/addon.json (name, menu), ${{ daemon: "src/main.mjs", simple: "src/main.py", external: "service.port" }[kind]}, addon/GUIDE.md, web/index.jsx
  rồi: npm install (một lần) → npm run zip → cài dist/${id}-0.1.0.zip ở Viewer Hub`);
