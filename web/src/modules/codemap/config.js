// Page config from GET /code-map/config, filled in by index.jsx before App renders.
export const config = { apiBase: "/code-map/api/graph", erdBase: "/code-map/api/erd", mcpUrl: "/code-map/mcp", pack: "", packs: [], source: false, readonly: false };

// Toast through the layout's M3 snackbar (web/src/md/snackbar.js).
export function notify(message) {
  if (!message) return;
  if (window.md?.snackbar) window.md.snackbar(message);
}
