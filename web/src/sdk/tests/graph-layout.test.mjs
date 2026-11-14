// node web/src/sdk/tests/graph-layout.test.mjs — layoutGraph (@vh/flow): no overlaps, groups fit children, edges
// follow the direction, and a 10 000-node system lays out fast.
import assert from "node:assert/strict";
import { layoutGraph } from "../graph-layout.js";

const overlap = (a, b) => a.x < b.x + b.width && b.x < a.x + a.width && a.y < b.y + b.height && b.y < a.y + a.height;

function checkLevel(nodes, pos) {
  const byParent = new Map();
  for (const n of nodes) {
    const key = n.parent || "";
    if (!byParent.has(key)) byParent.set(key, []);
    byParent.get(key).push(n.id);
  }
  for (const [parent, ids] of byParent) {
    for (let i = 0; i < ids.length; i += 1) {
      for (let j = i + 1; j < ids.length; j += 1) assert.ok(!overlap(pos[ids[i]], pos[ids[j]]), `${ids[i]} overlaps ${ids[j]}`);
    }
    if (parent) {
      const g = pos[parent];
      for (const id of ids) {
        const p = pos[id];
        assert.ok(p.x >= 0 && p.y >= 0 && p.x + p.width <= g.width + 0.01 && p.y + p.height <= g.height + 0.01, `${id} outside ${parent}`);
      }
    }
  }
}

// a chain goes left → right; with TB top → bottom
{
  const nodes = ["a", "b", "c"].map((id) => ({ id, width: 100, height: 40 }));
  const edges = [{ source: "a", target: "b" }, { source: "b", target: "c" }, { source: "c", target: "a" }];
  const lr = layoutGraph({ nodes, edges });
  assert.ok(lr.a.x < lr.b.x && lr.b.x < lr.c.x, "LR order");
  const tb = layoutGraph({ nodes, edges }, { direction: "TB" });
  assert.ok(tb.a.y < tb.b.y && tb.b.y < tb.c.y, "TB order");
  assert.equal(tb.a.width, 100);
  checkLevel(nodes, lr);
  checkLevel(nodes, tb);
}

// nested groups fit their children; an edge between leaves of two groups orders the groups
{
  const nodes = [
    { id: "g1", width: 120, height: 40 }, { id: "g2", width: 120, height: 40 },
    { id: "a", parent: "g1", width: 100, height: 40 }, { id: "b", parent: "g1", width: 100, height: 40 },
    { id: "g3", parent: "g2", width: 50, height: 40 }, { id: "c", parent: "g3", width: 100, height: 40 },
    { id: "loop1", parent: "loop2" }, { id: "loop2", parent: "loop1" }, { id: "orphan", parent: "missing" },
  ];
  const edges = [{ source: "a", target: "b" }, { source: "b", target: "c" }, { source: "x", target: "a" }, { source: "a", target: "a" }];
  for (const direction of ["LR", "TB"]) {
    const pos = layoutGraph({ nodes, edges }, { direction });
    assert.equal(Object.keys(pos).length, nodes.length);
    const fixed = nodes.map((n) => ({ ...n, parent: ["loop1", "loop2", "orphan"].includes(n.id) ? (n.id === "loop2" ? "loop1" : "") : n.parent }));
    checkLevel(fixed.filter((n) => !["loop1", "loop2"].includes(n.id)), pos);
    if (direction === "LR") assert.ok(pos.g1.x < pos.g2.x, "g1 before g2");
    else assert.ok(pos.g1.y < pos.g2.y, "g1 above g2");
    assert.ok(pos.g2.width >= pos.g3.width && pos.g3.height > 40);
  }
}

// a folded group keeps its size at its level; its inside is laid out and measured
{
  const nodes = [{ id: "g", width: 200, height: 80, folded: true }, { id: "x", width: 100, height: 40 },
    ...Array.from({ length: 30 }, (_, i) => ({ id: `c${i}`, parent: "g", width: 150, height: 50 }))];
  const pos = layoutGraph({ nodes, edges: [{ source: "c3", target: "x" }] });
  assert.equal(pos.g.width, 200);
  assert.equal(pos.g.height, 80);
  assert.ok(pos.g.inner.width > 400 && pos.g.inner.height > 200, "inner size");
  assert.ok(pos.x.x >= pos.g.x + 200, "x placed next to the folded box");
  assert.ok(pos.c29.x + pos.c29.width <= pos.g.inner.width && pos.c29.y >= 44, "children inside the open box, below the title");
}

// a big system: 40 domains × 5 services × 50 components, ~ 10 000 nodes and 15 000 edges
{
  const nodes = [], edges = [];
  let seed = 7;
  const rand = (n) => { seed = (seed * 1103515245 + 12345) % 2147483648; return seed % n; };
  for (let d = 0; d < 40; d += 1) {
    nodes.push({ id: `d${d}`, width: 200, height: 60 });
    for (let s = 0; s < 5; s += 1) {
      nodes.push({ id: `d${d}s${s}`, parent: `d${d}`, width: 180, height: 60 });
      for (let c = 0; c < 50; c += 1) {
        nodes.push({ id: `d${d}s${s}c${c}`, parent: `d${d}s${s}`, width: 160, height: 56 });
        if (c) edges.push({ source: `d${d}s${s}c${rand(c)}`, target: `d${d}s${s}c${c}` });
      }
    }
  }
  for (let i = 0; i < 5000; i += 1) edges.push({ source: `d${rand(40)}s${rand(5)}c${rand(50)}`, target: `d${rand(40)}s${rand(5)}c${rand(50)}` });
  const started = performance.now();
  const pos = layoutGraph({ nodes, edges });
  const ms = performance.now() - started;
  assert.equal(Object.keys(pos).length, nodes.length);
  checkLevel(nodes.filter((n) => !n.parent || n.parent.startsWith("d") && !n.parent.includes("s")), pos);
  assert.ok(ms < 3000, `too slow: ${ms.toFixed(0)} ms`);
  console.log(`graph-layout ok (${nodes.length} nodes, ${edges.length} edges: ${ms.toFixed(0)} ms)`);
}
