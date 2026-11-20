// API client: every call carries the pack the page was opened for (?pack=<id>).
import { config } from "./config.js";

function withPack(path) {
  if (!config.pack) return path;
  return `${path}${path.includes("?") ? "&" : "?"}pack=${encodeURIComponent(config.pack)}`;
}

export const api = async (path, options) => {
  const response = await fetch(`${config.apiBase}${withPack(path)}`, options);
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    const error = new Error(body.error?.message || body.message || `Request failed (${response.status})`);
    error.status = response.status;
    error.body = body;
    throw error;
  }
  return body;
};

const json = (method, body) => ({
  method,
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body ?? {}),
});
const id = (value) => encodeURIComponent(value);

export const businessApi = {
  tree: () => api("/business/tree"),
  item: (itemId) => api(`/business/items/${id(itemId)}`),
  featureData: (featureId) => api(`/business/features/${id(featureId)}/data`),
  flowData: (flowId) => api(`/business/flows/${id(flowId)}/data`),
  updateItem: (itemId, body) => api(`/business/items/${id(itemId)}`, json("PATCH", body)),
  flow: (flowId) => api(`/business/flows/${id(flowId)}`),
  updatePart: (flowId, part, body) => api(`/business/flows/${id(flowId)}/parts/${encodeURIComponent(part)}`, json("PATCH", body)),
  exportPack: (featureId, flags) => api(`/business/features/${id(featureId)}/ai-export?${new URLSearchParams(flags)}`, { method: "POST" }),
  checkImport: (featureId, text) => api(`/business/features/${id(featureId)}/ai-import/check`, json("POST", { text })),
  applyImport: (featureId, text) => api(`/business/features/${id(featureId)}/ai-import`, json("POST", { text })),
  exportOverview: (itemId, flags) => api(`/business/overview/ai-export?${new URLSearchParams({ item: itemId || "", ...flags })}`, { method: "POST" }),
  checkOverview: (itemId, text) => api("/business/overview/ai-import/check", json("POST", { item: itemId || "", text })),
  applyOverview: (itemId, text) => api("/business/overview/ai-import", json("POST", { item: itemId || "", text })),
  node: (nodeId) => api(`/business/nodes/${id(nodeId)}`),
  search: (query, signal) => api(`/business/search?q=${encodeURIComponent(query)}`, { signal }),
  kbStatus: () => api("/business/kb-status"),
  rules: (params = {}) => api(`/business/rules?${new URLSearchParams(params)}`),
  createRule: (body) => api("/business/rules", json("POST", body)),
  updateRule: (ruleId, body) => api(`/business/rules/${id(ruleId)}`, json("PATCH", body)),
  links: (params = {}) => api(`/business/links?${new URLSearchParams(params)}`),
  createLink: (body) => api("/business/links", json("POST", body)),
  updateLink: (linkId, body) => api(`/business/links/${id(linkId)}`, json("PATCH", body)),
  deleteLink: (linkId) => api(`/business/links/${id(linkId)}`, { method: "DELETE", headers: json("DELETE").headers }),
  gaps: (params = {}) => api(`/business/gaps?${new URLSearchParams(params)}`),
  dismissGap: (gap, undo = false) => api("/business/gaps/dismiss", json("POST", { gap, undo })),
  notes: (nodeId) => api(`/business/notes?node=${id(nodeId)}`),
  createNote: (nodeId, text) => api("/business/notes", json("POST", { node: nodeId, text })),
  updateNote: (noteId, body) => api(`/business/notes/${noteId}`, json("PATCH", body)),
  deleteNote: (noteId) => api(`/business/notes/${noteId}`, { method: "DELETE", headers: json("DELETE").headers }),
  snippet: (path, targetId) => api(`/snippet?path=${encodeURIComponent(path)}${targetId ? `&target_id=${encodeURIComponent(targetId)}` : ""}`),
};
