// Pure helpers for the ERD page (no React; checked with node in tests/erd-layout.test.mjs).
//
// Layout: tables in columns (layers), child tables (FK side) left of the tables they reference (PK side),
// so every relation reads left → right. Around a focus table the server gives each table's layer
// (-1 = references the focus, +1 = referenced by it, …); for a schema or system the layer is the longest
// FK path that ends at the table (cycles are cut after n passes). Tables without any relation go in a grid
// after the last column. Inside a column, one barycentre pass orders tables by the rows of their
// neighbours in the previous column to cut down crossings. No layout library: ~100 lines is enough here.

export const ERD_SIZE = { header: 52, row: 28, pad: 8, gapX: 140, gapY: 36 };
export const ERD_WIDTH = { tech: 300, logical: 400 };

export function visibleColumns(table, keysOnly) {
  return (table.columns || []).filter((column) => !keysOnly || column.pk || column.fk || column.referenced);
}

export function tableHeight(rows) {
  return ERD_SIZE.header + Math.max(1, rows) * ERD_SIZE.row + ERD_SIZE.pad;
}

// Layer per table id; null for a table with no relation in the diagram (schema / system views only).
export function erdLayers(model) {
  const tables = model.tables || [];
  const relations = (model.relations || []).filter((rel) => rel.from_table !== rel.to_table);
  const layers = new Map();
  if (model.mode === "table" && tables.every((table) => Number.isInteger(table.layer))) {
    tables.forEach((table) => layers.set(table.id, table.layer));
    return layers;
  }
  const linked = new Set(relations.flatMap((rel) => [rel.from_table, rel.to_table]));
  const rank = new Map(tables.map((table) => [table.id, 0]));
  const limit = tables.length;
  for (let pass = 0; pass < limit; pass += 1) {
    let changed = false;
    for (const rel of relations) {
      if (!rank.has(rel.from_table) || !rank.has(rel.to_table)) continue;
      const next = rank.get(rel.from_table) + 1;
      if (next > rank.get(rel.to_table) && next <= limit) { rank.set(rel.to_table, next); changed = true; }
    }
    if (!changed) break;
  }
  tables.forEach((table) => layers.set(table.id, linked.has(table.id) ? rank.get(table.id) : null));
  return layers;
}

// { id: { x, y } } for every table; `rowsOf(table)` is how many rows the node shows.
export function layoutErd(model, { width = ERD_WIDTH.tech, rowsOf = (table) => (table.columns || []).length } = {}) {
  const tables = model.tables || [];
  const layers = erdLayers(model);
  const neighbours = new Map(tables.map((table) => [table.id, []]));
  for (const rel of model.relations || []) {
    neighbours.get(rel.from_table)?.push(rel.to_table);
    neighbours.get(rel.to_table)?.push(rel.from_table);
  }
  const columns = new Map();
  const loose = [];
  for (const table of tables) {
    const layer = layers.get(table.id);
    if (layer === null || layer === undefined) { loose.push(table); continue; }
    if (!columns.has(layer)) columns.set(layer, []);
    columns.get(layer).push(table);
  }
  const keys = [...columns.keys()].sort((a, b) => a - b);
  const order = new Map();
  const positions = {};
  const height = (table) => tableHeight(rowsOf(table));
  let x = 0;
  keys.forEach((key, index) => {
    const items = columns.get(key);
    if (index > 0) {
      const score = (table) => {
        const seen = neighbours.get(table.id).filter((id) => order.has(id)).map((id) => order.get(id));
        return seen.length ? seen.reduce((sum, value) => sum + value, 0) / seen.length : Number.POSITIVE_INFINITY;
      };
      const scored = new Map(items.map((table) => [table.id, score(table)]));
      items.sort((a, b) => (scored.get(a.id) - scored.get(b.id)) || 0);
    }
    items.forEach((table, position) => order.set(table.id, position));
    const total = items.reduce((sum, table) => sum + height(table), 0) + ERD_SIZE.gapY * (items.length - 1);
    let y = -total / 2;
    for (const table of items) {
      positions[table.id] = { x, y };
      y += height(table) + ERD_SIZE.gapY;
    }
    x += width + ERD_SIZE.gapX;
  });
  if (loose.length) {
    const perRow = Math.max(1, Math.ceil(Math.sqrt(loose.length)));
    let y = keys.length ? -ERD_SIZE.header : 0;
    for (let start = 0; start < loose.length; start += perRow) {
      const row = loose.slice(start, start + perRow);
      row.forEach((table, index) => { positions[table.id] = { x: x + index * (width + ERD_SIZE.gapY), y }; });
      y += Math.max(...row.map(height)) + ERD_SIZE.gapY;
    }
  }
  return positions;
}

// Which side of each table an edge leaves and enters: right → left when the child is left of the parent,
// left → right when it is right of it, and right → right (a loop) in the same column.
export function edgeSides(fromX, toX) {
  if (fromX < toX) return { source: "r", target: "l" };
  if (fromX > toX) return { source: "l", target: "r" };
  return { source: "r", target: "r" };
}

// Logical name of a table or column in the chosen language ("tech": none).
export function logicalName(item, names) {
  if (!item || names === "tech") return "";
  const logical = item.logical || {};
  return logical[names] || logical.ja || logical.en || "";
}

// What the ERD route asks for: #/erd?table=…&depth=2&schema=…&names=en&cols=keys
export function erdParams(params = {}) {
  const depth = params.depth === "2" ? "2" : "1";
  const names = ["ja", "en", "tech"].includes(params.names) ? params.names : "ja";
  const cols = params.cols === "keys" ? "keys" : "all";
  return { table: params.table || "", schema: params.table ? "" : params.schema || "", system: params.table || params.schema ? "" : params.system || "", depth, names, cols };
}

export function erdHash(params) {
  const clean = erdParams(params);
  const query = new URLSearchParams();
  if (clean.table) query.set("table", clean.table);
  if (clean.schema) query.set("schema", clean.schema);
  if (clean.system) query.set("system", clean.system);
  if (clean.table && clean.depth !== "1") query.set("depth", clean.depth);
  if (clean.names !== "ja") query.set("names", clean.names);
  if (clean.cols !== "all") query.set("cols", clean.cols);
  const text = query.toString();
  return text ? `#/erd?${text}` : "#/erd";
}

export function erdFilename(scope, format) {
  const stem = String(scope || "erd").replace(/[^A-Za-z0-9._-]+/g, "_").replace(/^[._]+|[._]+$/g, "").slice(0, 80) || "erd";
  return `erd-${stem}.${format === "mermaid" ? "mmd" : format}`;
}
