// ERD canvas (React Flow): table nodes with one handle pair per column row, crow's-foot edges. Used by the flow page's
// "Dữ liệu" view (FlowData.jsx) on the model of /business/flows/<id>/data
// (erd.build(tables=[…])). `tags` (table id → "CRU") marks what the flow does to each table; `focus` centres one.
// The whole-database ERD browser is the "erd" addon (viewer-hub-addons/erd, same canvas ported to @vh/flow).
import React, { memo, useEffect, useRef } from "react";
import { Background, Controls, Handle, Position, ReactFlow, useEdgesState, useNodesInitialized, useNodesState, useReactFlow } from "@xyflow/react";
import { ERD_WIDTH, edgeSides, layoutErd, logicalName, visibleColumns } from "./lib/erd-layout.js";

const RULE_LABELS = { CASCADE: "xoá dây chuyền", "SET NULL": "đặt NULL", "SET DEFAULT": "đặt mặc định", RESTRICT: "chặn xoá" };

// ── Canvas: table nodes with one handle pair per column row ─────────────────────────────────────────

const HIDDEN_HANDLE = { isConnectable: false, className: "cm-erd__handle" };

// Only the handles an edge actually attaches to are rendered: React Flow measures every handle, and four
// per column row (80 tables x ~20 columns = ~6,400) made a big diagram take seconds to appear.
const HANDLE_KINDS = [["source", Position.Left, "s-l"], ["source", Position.Right, "s-r"], ["target", Position.Left, "t-l"], ["target", Position.Right, "t-r"]];
function RowHandles({ index, used }) {
  if (!used?.size) return null;
  return <>
    {HANDLE_KINDS.map(([type, position, prefix]) => {
      const id = `${prefix}-${index}`;
      return used.has(id) ? <Handle key={id} type={type} position={position} id={id} {...HIDDEN_HANDLE} /> : null;
    })}
  </>;
}

const ErdTableNode = memo(function ErdTableNode({ data }) {
  const { table, names, keysOnly, focus, width, onOpenNode, handles, tag } = data;
  const columns = visibleColumns(table, keysOnly);
  const title = logicalName(table, names);
  const hidden = (table.columns || []).length - columns.length;
  return <div className={`cm-erd-table${names !== "tech" ? " cm-erd-table--logical" : ""}${focus ? " is-focus" : ""}`} style={{ width }} title={table.comment || undefined}>
    <div className="cm-erd-table__head">
      <RowHandles index="head" used={handles} />
      <md-icon aria-hidden="true">table</md-icon>
      <span className="cm-erd-table__names">
        <strong className="cm-mono" title={table.qualified_name}>{table.name}</strong>
        <small>{[title, `${table.database}.${table.schema}`].filter(Boolean).join(" · ")}</small>
      </span>
      {tag ? <span className={`cm-erd-table__crud cm-mono${/[CUD]/.test(tag) ? " is-write" : ""}`} title="Luồng này làm gì với bảng: C tạo · R đọc · U sửa · D xoá">{tag}</span> : null}
      {onOpenNode ? <md-icon-button class="cm-erd-table__open nodrag" aria-label={`Mở graph của bảng ${table.name}`} title="Mở graph của bảng này"
        onClick={(event) => { event.stopPropagation(); onOpenNode(table.id); }}><md-icon>open_in_new</md-icon></md-icon-button> : null}
    </div>
    <div className="cm-erd-table__rows" role="list">
      {columns.map((column, index) => {
        const logical = logicalName(column, names);
        const tip = [`${column.name} ${column.type || ""}`.trim(), column.nullable ? "NULL" : "NOT NULL", logical, column.comment].filter(Boolean).join(" · ");
        return <div key={column.id} role="listitem" className={`cm-erd-row${column.pk ? " is-pk" : ""}${column.fk ? " is-fk" : ""}`} title={tip}>
          <RowHandles index={index} used={handles} />
          <span className="cm-erd-row__keys" aria-label={[column.pk ? "khoá chính" : "", column.fk ? "khoá ngoại" : ""].filter(Boolean).join(", ") || undefined}>
            {column.pk ? <md-icon class="cm-erd-row__pk">key</md-icon> : null}
            {column.fk ? <md-icon class="cm-erd-row__fk">link</md-icon> : null}
          </span>
          <span className={`cm-erd-row__name cm-mono${column.nullable ? "" : " is-required"}`}>{column.name}</span>
          <span className="cm-erd-row__type">{column.type}</span>
          {names !== "tech" ? <span className="cm-erd-row__logical">{logical}</span> : null}
        </div>;
      })}
      {!columns.length ? <div className="cm-erd-row cm-erd-row--none">{(table.columns || []).length ? "Không có cột khoá" : "Pack không có cột của bảng này"}</div> : null}
      {hidden > 0 ? <div className="cm-erd-row cm-erd-row--none">+ {hidden} cột khác</div> : null}
    </div>
  </div>;
});

const nodeTypes = { erdTable: ErdTableNode };

// Crow's-foot ends, drawn for the end of an edge (node on the right); the start is mirrored (auto-start-reverse).
function ErdMarkers() {
  return <svg className="cm-erd-markers" aria-hidden="true" width="0" height="0">
    <defs>
      <marker id="cm-erd-one" viewBox="0 0 20 20" refX="20" refY="10" markerWidth="20" markerHeight="20" markerUnits="userSpaceOnUse" orient="auto-start-reverse">
        <path d="M11 3 V17 M15 3 V17" />
      </marker>
      <marker id="cm-erd-zero-one" viewBox="0 0 20 20" refX="20" refY="10" markerWidth="20" markerHeight="20" markerUnits="userSpaceOnUse" orient="auto-start-reverse">
        <circle cx="7" cy="10" r="3.5" /><path d="M15 3 V17" />
      </marker>
      <marker id="cm-erd-many" viewBox="0 0 20 20" refX="20" refY="10" markerWidth="20" markerHeight="20" markerUnits="userSpaceOnUse" orient="auto-start-reverse">
        <circle cx="5" cy="10" r="3.5" /><path d="M10 10 L20 3 M10 10 L20 10 M10 10 L20 17" />
      </marker>
    </defs>
  </svg>;
}

function buildGraph(model, { names, keysOnly, onOpenNode, tags, focus }) {
  const width = names === "tech" ? ERD_WIDTH.tech : ERD_WIDTH.logical;
  const rowsOf = (table) => {
    const shown = visibleColumns(table, keysOnly).length;
    return Math.max(1, shown) + ((table.columns || []).length > shown && shown ? 1 : 0);
  };
  const positions = layoutErd(model, { width, rowsOf });
  const rowIndex = new Map(model.tables.map((table) => [table.id, new Map(visibleColumns(table, keysOnly).map((column, index) => [column.id, index]))]));
  const edges = [];
  for (const rel of model.relations) {
    const from = positions[rel.from_table];
    const to = positions[rel.to_table];
    if (!from || !to) continue;
    const sides = edgeSides(from.x, to.x);
    const rule = RULE_LABELS[rel.delete_rule];
    rel.from_column_ids.forEach((columnId, index) => {
      const source = rowIndex.get(rel.from_table)?.get(columnId);
      const target = rowIndex.get(rel.to_table)?.get(rel.to_column_ids[index]);
      edges.push({
        id: `${rel.id}#${index}`, source: rel.from_table, target: rel.to_table, type: "smoothstep",
        sourceHandle: `s-${sides.source}-${source ?? "head"}`, targetHandle: `t-${sides.target}-${target ?? "head"}`,
        label: index === 0 ? `${rel.label}${rule ? ` · ${rule}` : ""}` : undefined,
        markerStart: rel.cardinality === "one-to-one" ? "cm-erd-zero-one" : "cm-erd-many",
        markerEnd: rel.optional ? "cm-erd-zero-one" : "cm-erd-one",
        className: `cm-erd-edge${rel.delete_rule === "CASCADE" ? " is-cascade" : ""}${rel.source === "ddl" ? " is-ddl" : ""}`,
        labelBgPadding: [6, 3], labelBgBorderRadius: 4,
        pathOptions: { borderRadius: 10, offset: 24 },
      });
    });
  }
  const handles = new Map();
  for (const edge of edges) {
    if (!handles.has(edge.source)) handles.set(edge.source, new Set());
    if (!handles.has(edge.target)) handles.set(edge.target, new Set());
    handles.get(edge.source).add(edge.sourceHandle);
    handles.get(edge.target).add(edge.targetHandle);
  }
  const nodes = model.tables.map((table) => ({
    id: table.id, type: "erdTable", position: positions[table.id] || { x: 0, y: 0 },
    data: { table, names, keysOnly, width, focus: table.id === (focus || model.focus), onOpenNode, handles: handles.get(table.id), tag: tags?.[table.id] || "" },
  }));
  return { nodes, edges };
}

const FIT = { padding: 0.12, maxZoom: 1, duration: 250 };

// Fit once React Flow has measured the nodes of a new diagram (fitting earlier sees zero-size nodes).
function AutoFit({ signature }) {
  const ready = useNodesInitialized();
  const flow = useReactFlow();
  useEffect(() => { if (ready) flow.fitView(FIT); }, [ready, signature, flow]);
  return null;
}

// Pans to the focused table (keeps the zoom) once it is drawn.
function FocusTable({ id, nodes }) {
  const flow = useReactFlow();
  const ready = useNodesInitialized();
  useEffect(() => {
    const node = id && ready ? flow.getNode(id) : null;
    if (!node) return;
    const width = node.measured?.width || node.width || 300;
    const height = node.measured?.height || node.height || 120;
    flow.setCenter(node.position.x + width / 2, node.position.y + height / 2, { zoom: Math.max(flow.getZoom(), 0.8), duration: 300 });
  }, [id, ready, nodes, flow]);
  return null;
}

export function ErdCanvas({ model, names = "ja", keysOnly = false, onFocus = () => {}, onOpenNode = null, fitRef = { current: null }, className = "", tags = null, focus = "" }) {
  const [nodes, setNodes, onNodesChange] = useNodesState([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState([]);
  const instance = useRef(null);
  useEffect(() => {
    const graph = buildGraph(model, { names, keysOnly, onOpenNode, tags, focus });
    setNodes(graph.nodes);
    setEdges(graph.edges);
  }, [model, names, keysOnly, onOpenNode, tags, focus, setNodes, setEdges]);
  fitRef.current = () => instance.current?.fitView(FIT);
  return <div className={`cm-canvas cm-erd__canvas ${className}`.trim()}>
    <ErdMarkers />
    <ReactFlow nodes={nodes} edges={edges} nodeTypes={nodeTypes} onNodesChange={onNodesChange} onEdgesChange={onEdgesChange}
      onInit={(value) => { instance.current = value; }} onNodeClick={(_, node) => onFocus(node.id)}
      nodesConnectable={false} minZoom={0.1} maxZoom={1.6}
      proOptions={{ hideAttribution: true }}>
      <Background gap={20} size={1.2} />
      <Controls showInteractive={false} />
      {focus ? <FocusTable id={focus} nodes={nodes.length} /> : <AutoFit signature={`${model.scope}|${model.depth}|${names}|${keysOnly}`} />}
    </ReactFlow>
  </div>;
}
