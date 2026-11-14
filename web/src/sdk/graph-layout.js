// Layered ("Sugiyama-lite") layout for big nested graphs: what @vh/flow's layoutGraph() runs in a Web Worker.
// Pure functions, no DOM: also run by web/src/sdk/tests/graph-layout.test.mjs under Node.
//
// input   nodes: [{id, parent?, width, height, folded?}]  (parent: another node in the list = it is drawn inside it;
//         folded: a group shown closed, width / height at its parent's level, its inside still laid out)
//         edges: [{source, target}]
// options direction "LR" | "TB", nodeGap, rankGap, padding, header (room for a group's title), maxColumn
// output  { [id]: {x, y, width, height, inner?} } with x / y relative to the parent's top-left (React Flow sub-flows); a
//         node with children gets the size that fits them (a folded one keeps its size; inner: {width, height} open).
//
// Each edge is placed once, at the level of the lowest common ancestor of its ends (an edge between two leaves in
// different groups pulls those two groups together). Per level: connected components; cycles broken by DFS; ranks by
// longest path; order by barycenter sweeps; ranks wider than maxColumn wrap into several columns; components are
// packed in rows. Linear-ish in nodes + edges: 10 000 nodes take well under a second.

const DEFAULTS = { direction: "LR", nodeGap: 28, rankGap: 80, padding: 24, header: 44, maxColumn: 0, componentGap: 60 };

export function layoutGraph(input, options = {}) {
  const opt = { ...DEFAULTS, ...options };
  const across = opt.direction === "TB"; // TB: lay out as LR with width / height swapped, swap back at the end
  const nodes = new Map();
  for (const n of input.nodes || []) {
    if (!n || n.id == null || nodes.has(String(n.id))) continue;
    const width = Math.max(10, Number(n.width) || 160), height = Math.max(10, Number(n.height) || 60);
    nodes.set(String(n.id), { id: String(n.id), parent: n.parent == null ? "" : String(n.parent), w: across ? height : width, h: across ? width : height, kids: [], folded: !!n.folded });
  }
  const top = [];
  for (const n of nodes.values()) {
    if (n.parent && (!nodes.has(n.parent) || n.parent === n.id)) n.parent = "";
  }
  // a parent loop (a inside b inside a) is cut at the first node met again
  for (const n of nodes.values()) {
    const seen = new Set([n.id]);
    let p = n.parent;
    while (p) {
      if (seen.has(p)) { n.parent = ""; break; }
      seen.add(p);
      p = nodes.get(p).parent;
    }
  }
  for (const n of nodes.values()) (n.parent ? nodes.get(n.parent).kids : top).push(n.id);

  // depth and ancestor chains → the level (lowest common ancestor) each edge belongs to
  const depth = new Map();
  const depthOf = (id) => {
    if (depth.has(id)) return depth.get(id);
    const chain = [];
    let cur = id;
    while (cur && !depth.has(cur)) { chain.push(cur); cur = nodes.get(cur).parent; }
    let d = cur ? depth.get(cur) : -1;
    for (let i = chain.length - 1; i >= 0; i -= 1) depth.set(chain[i], ++d);
    return depth.get(id);
  };
  const levelEdges = new Map(); // parent id ("" = top) → Map("a\tb" → [a, b])
  for (const e of input.edges || []) {
    let a = String(e?.source ?? ""), b = String(e?.target ?? "");
    if (!nodes.has(a) || !nodes.has(b) || a === b) continue;
    let da = depthOf(a), db = depthOf(b);
    while (da > db) { a = nodes.get(a).parent; da -= 1; }
    while (db > da) { b = nodes.get(b).parent; db -= 1; }
    if (a === b) continue; // one end inside the other
    while (nodes.get(a).parent !== nodes.get(b).parent) { a = nodes.get(a).parent; b = nodes.get(b).parent; }
    const level = nodes.get(a).parent;
    if (!levelEdges.has(level)) levelEdges.set(level, new Map());
    levelEdges.get(level).set(`${a}\t${b}`, [a, b]);
  }

  const out = {};
  // children first (post-order, iterative: deep nesting must not overflow the stack)
  const order = [];
  const stack = top.map((id) => [id, false]);
  while (stack.length) {
    const [id, done] = stack.pop();
    if (done) { order.push(id); continue; }
    stack.push([id, true]);
    for (const k of nodes.get(id).kids) stack.push([k, false]);
  }
  const place = (ids, level) => layoutLevel(ids.map((id) => nodes.get(id)), [...(levelEdges.get(level)?.values() || [])], opt);
  for (const id of order) {
    const n = nodes.get(id);
    if (!n.kids.length) continue;
    const inner = place(n.kids, id);
    // TB is laid out transposed: the title goes on the (later) top, which is the left side here
    const openW = inner.width + 2 * opt.padding + (across ? opt.header : 0);
    const openH = inner.height + 2 * opt.padding + (across ? 0 : opt.header);
    if (n.folded) n.inner = { w: openW, h: openH };
    else { n.w = Math.max(n.w, openW); n.h = Math.max(n.h, openH); }
    const dx = opt.padding + (across ? opt.header : 0), dy = opt.padding + (across ? 0 : opt.header);
    for (const [cid, p] of Object.entries(inner.pos)) out[cid] = { x: p.x + dx, y: p.y + dy };
  }
  const root = place(top, "");
  for (const [id, p] of Object.entries(root.pos)) out[id] = { x: p.x, y: p.y };
  for (const n of nodes.values()) {
    const p = out[n.id] || { x: 0, y: 0 };
    out[n.id] = across ? { x: p.y, y: p.x, width: n.h, height: n.w } : { x: p.x, y: p.y, width: n.w, height: n.h };
    if (n.inner) out[n.id].inner = across ? { width: n.inner.h, height: n.inner.w } : { width: n.inner.w, height: n.inner.h };
  }
  return out;
}

/** One level: siblings with sizes (w, h) and the edges between them → {pos: {id: {x, y}}, width, height}. */
function layoutLevel(items, edges, opt) {
  if (!items.length) return { pos: {}, width: 0, height: 0 };
  const index = new Map(items.map((n, i) => [n.id, i]));
  const parentOf = items.map((_, i) => i);
  const find = (i) => { while (parentOf[i] !== i) { parentOf[i] = parentOf[parentOf[i]]; i = parentOf[i]; } return i; };
  const out = items.map(() => []), inn = items.map(() => []);
  for (const [a, b] of edges) {
    const i = index.get(a), j = index.get(b);
    if (i == null || j == null || i === j) continue;
    out[i].push(j); inn[j].push(i);
    parentOf[find(i)] = find(j);
  }
  const groups = new Map();
  items.forEach((_, i) => {
    const r = find(i);
    if (!groups.has(r)) groups.set(r, []);
    groups.get(r).push(i);
  });
  const boxes = [...groups.values()].map((members) => component(members, items, out, inn, opt));
  return pack(boxes, opt);
}

function component(members, items, out, inn, opt) {
  if (members.length === 1) {
    const n = items[members[0]];
    return { pos: { [n.id]: { x: 0, y: 0 } }, width: n.w, height: n.h };
  }
  const inSet = new Set(members);
  // break cycles: DFS from each unvisited node; an edge to a node on the stack is reversed
  const state = new Map(); // 1 on stack, 2 done
  const succ = new Map(members.map((i) => [i, []])), pred = new Map(members.map((i) => [i, []]));
  const addEdge = (a, b) => { if (a !== b) { succ.get(a).push(b); pred.get(b).push(a); } };
  const roots = [...members].sort((a, b) => inn[a].length - inn[b].length || a - b);
  for (const start of roots) {
    if (state.has(start)) continue;
    const stack = [[start, 0]];
    state.set(start, 1);
    while (stack.length) {
      const top = stack[stack.length - 1];
      const [v, k] = top;
      if (k < out[v].length) {
        top[1] += 1;
        const w = out[v][k];
        if (!inSet.has(w)) continue;
        const s = state.get(w);
        if (s === 1) addEdge(w, v);           // back edge: reverse it
        else { addEdge(v, w); if (!s) { state.set(w, 1); stack.push([w, 0]); } }
      } else {
        state.set(v, 2);
        stack.pop();
      }
    }
  }
  // ranks: longest path from the sources (Kahn order), then pull pure sources next to their first successor
  const indeg = new Map(members.map((i) => [i, pred.get(i).length]));
  const queue = members.filter((i) => !indeg.get(i));
  const rank = new Map(members.map((i) => [i, 0]));
  for (let q = 0; q < queue.length; q += 1) {
    const v = queue[q];
    for (const w of succ.get(v)) {
      rank.set(w, Math.max(rank.get(w), rank.get(v) + 1));
      indeg.set(w, indeg.get(w) - 1);
      if (!indeg.get(w)) queue.push(w);
    }
  }
  for (const v of members) {
    if (!pred.get(v).length && succ.get(v).length) rank.set(v, Math.max(0, Math.min(...succ.get(v).map((w) => rank.get(w))) - 1));
  }
  const ranks = [];
  for (const v of queue) (ranks[rank.get(v)] ||= []).push(v);
  const layers = ranks.filter(Boolean);
  // order inside each rank: barycenter sweeps (down by predecessors, up by successors)
  const posIn = new Map();
  const renumber = (layer) => layer.forEach((v, i) => posIn.set(v, i));
  layers.forEach(renumber);
  const sweep = (layer, near) => {
    const key = new Map(layer.map((v) => {
      const ns = near.get(v);
      return [v, ns.length ? ns.reduce((s, w) => s + posIn.get(w), 0) / ns.length : posIn.get(v)];
    }));
    layer.sort((a, b) => key.get(a) - key.get(b) || posIn.get(a) - posIn.get(b));
    renumber(layer);
  };
  for (let pass = 0; pass < 6; pass += 1) {
    if (pass % 2 === 0) for (let r = 1; r < layers.length; r += 1) sweep(layers[r], pred);
    else for (let r = layers.length - 2; r >= 0; r -= 1) sweep(layers[r], succ);
  }
  // wrap tall ranks into several columns (a hub with 300 callees is not one 20 000 px column)
  const maxColumn = opt.maxColumn || Math.max(8, Math.ceil(Math.sqrt(members.length) * 1.5));
  const columns = [];
  for (const layer of layers) for (let i = 0; i < layer.length; i += maxColumn) columns.push(layer.slice(i, i + maxColumn));
  // x per column; y: follow the predecessors' centre when there is room, keep order, no overlap
  const pos = {};
  const centre = new Map();
  const cols = []; // {x, width, top, bottom, ids}
  let x = 0;
  for (const column of columns) {
    const width = Math.max(...column.map((v) => items[v].w));
    let floor = -Infinity, top = Infinity, bottom = -Infinity;
    for (const v of column) {
      const n = items[v];
      const ps = pred.get(v).filter((w) => centre.has(w));
      const want = ps.length ? ps.reduce((s, w) => s + centre.get(w), 0) / ps.length - n.h / 2 : floor === -Infinity ? 0 : floor;
      const y = floor === -Infinity ? want : Math.max(want, floor);
      pos[n.id] = { x: x + (width - n.w) / 2, y };
      centre.set(v, y + n.h / 2);
      floor = y + n.h + opt.nodeGap;
      top = Math.min(top, y); bottom = Math.max(bottom, y + n.h);
    }
    cols.push({ x, width, top, bottom, ids: column.map((v) => items[v].id) });
    x += width + opt.rankGap;
  }
  let minY = Infinity, maxY = -Infinity;
  for (const c of cols) { minY = Math.min(minY, c.top); maxY = Math.max(maxY, c.bottom); }
  const width = Math.max(0, x - opt.rankGap), height = maxY - minY;
  // a long chain of ranks: wrap the columns into bands (read left → right, then the next band), about 2 : 1 overall
  const area = cols.reduce((s, c) => s + (c.width + opt.rankGap) * (c.bottom - c.top + opt.nodeGap), 0);
  const target = Math.max(...cols.map((c) => c.width), Math.sqrt(area * 2.2));
  if (cols.length > 3 && width > target * 1.4) {
    let bandX = 0, bandY = 0, bandH = 0, outW = 0;
    for (const c of cols) {
      if (bandX > 0 && bandX + c.width > target) { bandX = 0; bandY += bandH + opt.rankGap; bandH = 0; }
      for (const id of c.ids) pos[id] = { x: pos[id].x - c.x + bandX, y: pos[id].y - c.top + bandY };
      bandX += c.width + opt.rankGap;
      bandH = Math.max(bandH, c.bottom - c.top);
      outW = Math.max(outW, bandX - opt.rankGap);
    }
    return { pos, width: outW, height: bandY + bandH };
  }
  for (const v of members) pos[items[v].id].y -= minY;
  return { pos, width, height };
}

/** Components → rows ("shelves"), biggest first, rows about as wide as the whole is tall. */
function pack(boxes, opt) {
  if (boxes.length === 1) return boxes[0];
  boxes.sort((a, b) => b.height * b.width - a.height * a.width);
  const gap = opt.componentGap;
  const area = boxes.reduce((s, b) => s + (b.width + gap) * (b.height + gap), 0);
  const rowWidth = Math.max(Math.max(...boxes.map((b) => b.width)), Math.sqrt(area) * 1.6);
  const pos = {};
  let x = 0, y = 0, rowHeight = 0, width = 0;
  for (const b of boxes) {
    if (x > 0 && x + b.width > rowWidth) { x = 0; y += rowHeight + gap; rowHeight = 0; }
    for (const [id, p] of Object.entries(b.pos)) pos[id] = { x: p.x + x, y: p.y + y };
    x += b.width + gap;
    rowHeight = Math.max(rowHeight, b.height);
    width = Math.max(width, x - gap);
  }
  return { pos, width, height: y + rowHeight };
}
