import assert from "node:assert/strict";
import { edgeSides, erdFilename, erdHash, erdLayers, erdParams, layoutErd, logicalName, visibleColumns } from "../lib/erd-layout.js";
import { parseRoute, routeHash } from "../lib/text.js";

// Routes
assert.deepEqual(parseRoute("#/erd"), { view: "erd", id: null, params: {} });
assert.deepEqual(parseRoute("#/erd?table=table%3ADB1%3AORDERS&depth=2"), { view: "erd", id: null, params: { table: "table:DB1:ORDERS", depth: "2" } });
assert.equal(routeHash("erd"), "#/erd");
assert.equal(erdHash({ table: "table:DB1:ORDERS", depth: "2", names: "en" }), "#/erd?table=table%3ADB1%3AORDERS&depth=2&names=en");
assert.equal(erdHash({ schema: "DB1.APP", depth: "2" }), "#/erd?schema=DB1.APP");  // depth only around a table
assert.equal(erdHash({}), "#/erd");
assert.deepEqual(erdParams({ table: "T", schema: "S", depth: "9", names: "xx", cols: "keys" }),
  { table: "T", schema: "", system: "", depth: "1", names: "ja", cols: "keys" });
assert.equal(erdFilename("DB1.APP.ORDERS", "mermaid"), "erd-DB1.APP.ORDERS.mmd");
assert.equal(erdFilename("../x y", "dbml"), "erd-x_y.dbml");

// Names and columns
assert.equal(logicalName({ logical: { ja: "注文", en: "Order" } }, "en"), "Order");
assert.equal(logicalName({ logical: { en: "Order" } }, "ja"), "Order");
assert.equal(logicalName({ logical: { ja: "注文" } }, "tech"), "");
const cols = [{ id: "a", pk: true }, { id: "b", fk: true }, { id: "c" }, { id: "d", referenced: true }];
assert.deepEqual(visibleColumns({ columns: cols }, true).map((c) => c.id), ["a", "b", "d"]);
assert.equal(visibleColumns({ columns: cols }, false).length, 4);

// Layers: around a focus the server's layers; for a schema the longest FK path, loose tables apart.
const focus = { mode: "table", tables: [{ id: "o", layer: 0 }, { id: "l", layer: -1 }], relations: [] };
assert.deepEqual([...erdLayers(focus)], [["o", 0], ["l", -1]]);
const schema = {
  mode: "schema",
  tables: ["a", "b", "c", "d", "x"].map((id) => ({ id, columns: [{ id: `${id}1` }] })),
  relations: [
    { from_table: "a", to_table: "b" }, { from_table: "b", to_table: "c" }, { from_table: "a", to_table: "c" },
    { from_table: "d", to_table: "c" }, { from_table: "c", to_table: "a" }, // a cycle must not loop forever
  ],
};
const layers = erdLayers(schema);
assert.equal(layers.get("x"), null);
assert.ok(layers.get("b") > layers.get("a") || layers.get("a") > 0);
const positions = layoutErd(schema, { width: 300 });
assert.equal(Object.keys(positions).length, 5);
assert.ok(positions.x.x >= Math.max(positions.a.x, positions.b.x, positions.c.x, positions.d.x)); // loose grid after the columns
const chain = layoutErd({ mode: "schema", tables: [{ id: "child", columns: [] }, { id: "parent", columns: [] }], relations: [{ from_table: "child", to_table: "parent" }] });
assert.ok(chain.child.x < chain.parent.x, "FK side left of PK side");

assert.deepEqual(edgeSides(0, 400), { source: "r", target: "l" });
assert.deepEqual(edgeSides(400, 0), { source: "l", target: "r" });
assert.deepEqual(edgeSides(0, 0), { source: "r", target: "r" });
console.log("erd-layout ok");
