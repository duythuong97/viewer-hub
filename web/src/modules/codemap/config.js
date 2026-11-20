// Page config from GET /code-map/config, filled in by index.jsx before App renders.
export const config = { apiBase: "/code-map/api/graph", mcpUrl: "/code-map/mcp", pack: "", packs: [], source: false, readonly: false, erdAddon: "" };

// Toast through the layout's M3 snackbar (web/src/md/snackbar.js).
export function notify(message) {
  if (!message) return;
  if (window.md?.snackbar) window.md.snackbar(message);
}

// The "erd" addon page (whole-database ERD) with a deep link, or "" when it is not installed / locked.
export function erdAddonUrl(query = {}) {
  if (!config.erdAddon) return "";
  const params = new URLSearchParams(Object.entries({ ...query, pack: config.pack }).filter(([, value]) => value));
  const text = params.toString();
  return `${config.erdAddon}/${text ? `?${text}` : ""}`;
}
