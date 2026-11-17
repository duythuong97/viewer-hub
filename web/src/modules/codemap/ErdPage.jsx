// ERD of the pack's database: tables linked by foreign keys around a focus table (depth 1–2), or a whole schema.
// Data: GET /code-map/api/erd (viewer_hub/codemap/erd.py). Route: #/erd?table=…&depth=…&schema=…&names=…&cols=…
import React, { memo, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Background, Controls, Handle, Position, ReactFlow, useEdgesState, useNodesInitialized, useNodesState, useReactFlow } from "@xyflow/react";
import { erdApi } from "./api.js";
import { Button, Dialog, Empty, ErrorBanner, IconButton, InputChip, Progress, Segmented, Select } from "../../md/react.jsx";
import { copyText, downloadText } from "./common.jsx";
import { ERD_WIDTH, edgeSides, erdFilename, erdHash, erdParams, layoutErd, logicalName, visibleColumns } from "./lib/erd-layout.js";

const NAME_OPTIONS = [["ja", "日本語"], ["en", "English"], ["tech", "Tên kỹ thuật"]];
const DEPTH_OPTIONS = [["1", "1 bước"], ["2", "2 bước"]];
const COLUMN_OPTIONS = [["all", "Tất cả cột"], ["keys", "Chỉ cột khoá"]];
const ANY_SCHEMA = "*";
const RULE_LABELS = { CASCADE: "xoá dây chuyền", "SET NULL": "đặt NULL", "SET DEFAULT": "đặt mặc định", RESTRICT: "chặn xoá" };

// ── Table picker (shared M3 search bar + results menu) ─────────────────────────────────────────────

function TablePicker({ schema, onPick }) {
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(false);
  const [state, setState] = useState({ loading: false, error: "", tables: [], total: 0 });
  const [active, setActive] = useState(0);
  const input = useRef(null);
  const box = useRef(null);

  useEffect(() => {
    if (!open) return undefined;
    const controller = new AbortController();
    const timer = setTimeout(async () => {
      setState((current) => ({ ...current, loading: true, error: "" }));
      try {
        const body = await erdApi.tables(query.trim(), schema, controller.signal);
        setState({ loading: false, error: "", tables: body.tables || [], total: body.total || 0 });
        setActive(0);
      } catch (error) {
        if (error.name !== "AbortError") setState({ loading: false, error: error.message, tables: [], total: 0 });
      }
    }, 160);
    return () => { clearTimeout(timer); controller.abort(); };
  }, [query, schema, open]);

  useEffect(() => {
    const onClick = (event) => { if (!box.current?.contains(event.target)) setOpen(false); };
    document.addEventListener("mousedown", onClick);
    return () => document.removeEventListener("mousedown", onClick);
  }, []);

  function pick(table) {
    if (!table) return;
    setOpen(false);
    setQuery("");
    input.current?.blur();
    onPick(table.id);
  }

  function onKeyDown(event) {
    if (event.key === "ArrowDown") { setActive((value) => Math.min(value + 1, state.tables.length - 1)); event.preventDefault(); }
    else if (event.key === "ArrowUp") { setActive((value) => Math.max(value - 1, 0)); event.preventDefault(); }
    else if (event.key === "Enter") { pick(state.tables[active]); event.preventDefault(); }
    else if (event.key === "Escape") { setOpen(false); input.current?.blur(); }
  }

  return <div className="cm-search cm-erd__picker" ref={box}>
    <div className="md-search-bar cm-search__bar">
      <md-icon>table</md-icon>
      <input ref={input} type="search" value={query} autoComplete="off" spellCheck={false} aria-label="Chọn bảng" role="combobox"
        aria-expanded={open} placeholder="Chọn bảng: tên kỹ thuật hoặc tên logic (日本語 / English)…"
        onChange={(event) => { setQuery(event.target.value); setOpen(true); }} onFocus={() => setOpen(true)} onKeyDown={onKeyDown} />
      <md-icon-button class="md-search-bar__clear" aria-label="Xoá nội dung tìm" hidden={!query || undefined}
        onClick={() => { setQuery(""); input.current?.focus(); }}><md-icon>close</md-icon></md-icon-button>
      <md-filled-icon-button class="md-search-bar__submit" aria-label="Mở bảng đang chọn" title="Mở bảng đang chọn (Enter)"
        onClick={() => { if (open && state.tables[active]) pick(state.tables[active]); else { setOpen(true); input.current?.focus(); } }}>
        <md-icon>search</md-icon></md-filled-icon-button>
    </div>
    {open ? <div className="cm-search__menu" role="listbox">
      {state.loading ? <md-linear-progress indeterminate /> : null}
      {state.error ? <p className="cm-search__empty">{state.error}</p> : null}
      {!state.error && !state.tables.length ? <p className="cm-search__empty">{state.loading ? "Đang tìm…" : `Không có bảng nào khớp “${query}”.`}</p> : null}
      {state.tables.length ? <h6 className="cm-search__group">Bảng{state.total > state.tables.length ? ` · ${state.tables.length}/${state.total}` : ""}</h6> : null}
      {state.tables.map((table, index) => <button key={table.id} type="button" role="option" aria-selected={index === active}
        className={`cm-hit${index === active ? " is-active" : ""}`} onMouseEnter={() => setActive(index)} onClick={() => pick(table)}>
        <span className="cm-hit__icon"><md-icon>table</md-icon></span>
        <span className="cm-hit__text"><b className="cm-mono">{table.name}</b>
          <small>{[`${table.database}.${table.schema}`, table.logical?.ja, table.logical?.en].filter(Boolean).join(" · ")}</small></span>
      </button>)}
    </div> : null}
  </div>;
}

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
  const { table, names, keysOnly, focus, width, onOpenNode, handles } = data;
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
      <md-icon-button class="cm-erd-table__open nodrag" aria-label={`Mở graph của bảng ${table.name}`} title="Mở graph của bảng này"
        onClick={(event) => { event.stopPropagation(); onOpenNode(table.id); }}><md-icon>open_in_new</md-icon></md-icon-button>
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

function buildGraph(model, { names, keysOnly, onOpenNode }) {
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
    data: { table, names, keysOnly, width, focus: table.id === model.focus, onOpenNode, handles: handles.get(table.id) },
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

function ErdCanvas({ model, names, keysOnly, onFocus, onOpenNode, fitRef }) {
  const [nodes, setNodes, onNodesChange] = useNodesState([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState([]);
  const instance = useRef(null);
  useEffect(() => {
    const graph = buildGraph(model, { names, keysOnly, onOpenNode });
    setNodes(graph.nodes);
    setEdges(graph.edges);
  }, [model, names, keysOnly, onOpenNode, setNodes, setEdges]);
  fitRef.current = () => instance.current?.fitView(FIT);
  return <div className="cm-canvas cm-erd__canvas">
    <ErdMarkers />
    <ReactFlow nodes={nodes} edges={edges} nodeTypes={nodeTypes} onNodesChange={onNodesChange} onEdgesChange={onEdgesChange}
      onInit={(value) => { instance.current = value; }} onNodeClick={(_, node) => onFocus(node.id)}
      nodesConnectable={false} minZoom={0.1} maxZoom={1.6}
      proOptions={{ hideAttribution: true }}>
      <Background gap={20} size={1.2} />
      <Controls showInteractive={false} />
      <AutoFit signature={`${model.scope}|${model.depth}|${names}|${keysOnly}`} />
    </ReactFlow>
  </div>;
}

// ── Export dialog (Mermaid / DBML): preview, copy, download ─────────────────────────────────────────

const FORMAT_LABELS = { mermaid: "Mermaid", dbml: "DBML" };
const FORMAT_HINTS = {
  mermaid: "Sơ đồ erDiagram của Mermaid: dán vào Markdown của GitLab, GitHub, Confluence hoặc VS Code (có extension Mermaid) để xem.",
  dbml: "DBML cho dbdiagram.io: dán vào trình soạn của dbdiagram (hoặc dùng @dbml/cli) để xem và chỉnh sơ đồ.",
};

function ExportDialog({ format, request, scope, onClose, notify }) {
  const [text, setText] = useState("");
  const [error, setError] = useState("");
  const preview = useRef(null);
  useEffect(() => {
    let live = true;
    erdApi.text(request, format).then((value) => { if (live) setText(value); }).catch((reason) => { if (live) setError(reason.message); });
    return () => { live = false; };
  }, [format, request]);
  const filename = erdFilename(scope, format);
  const actions = (close) => <>
    <Button onClick={close}>Đóng</Button>
    <Button variant="outlined" icon="content_copy" disabled={!text}
      onClick={async () => notify(await copyText(text, preview.current) ? "Đã sao chép" : "Đã chọn nội dung, nhấn Ctrl+C để sao chép")}>Sao chép</Button>
    <Button variant="filled" icon="download" disabled={!text} onClick={() => { downloadText(filename, text); notify(`Đã tải ${filename}`); }}>Tải file</Button>
  </>;
  return <Dialog headline={`Xuất ${FORMAT_LABELS[format]}`} icon="ios_share" onClose={onClose} actions={actions} wide>
    <p className="md-muted">{FORMAT_HINTS[format]}</p>
    {error ? <ErrorBanner>{error}</ErrorBanner> : null}
    <label className="cm-code-field"><span className="cm-label">Xem trước · {filename}</span>
      <textarea ref={preview} className="cm-code" rows={16} readOnly value={text || (error ? "" : "Đang tạo…")} spellCheck={false} /></label>
  </Dialog>;
}

// ── Filters (shared filter bar + "Bộ lọc" panel) ────────────────────────────────────────────────────

function ErdFilters({ params, schemas, summary, onApply }) {
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState(params);
  const defaults = { schema: "", depth: "1", names: "ja", cols: "all" };
  const chips = [
    params.schema ? ["schema", `Schema: ${params.schema}`] : null,
    params.table && params.depth !== "1" ? ["depth", `Độ sâu: ${params.depth}`] : null,
    params.names !== "ja" ? ["names", `Tên: ${NAME_OPTIONS.find(([key]) => key === params.names)?.[1]}`] : null,
    params.cols !== "all" ? ["cols", "Chỉ cột khoá"] : null,
  ].filter(Boolean);
  function toggle() {
    if (!open) setDraft(params);
    setOpen(!open);
  }
  function apply() {
    // A schema picked here opens the whole schema; "Theo bảng" keeps the focus table.
    onApply(draft.schema && draft.schema !== params.schema ? { ...draft, table: "" } : draft);
    setOpen(false);
  }
  // md-outlined-select shows nothing for an empty value, so "no schema" is a sentinel.
  const schemaOptions = [[ANY_SCHEMA, params.table ? "Theo bảng đang chọn" : "Chưa chọn schema"],
    ...schemas.map((item) => [item.id, `${item.id} · ${item.tables} bảng`])];
  return <>
    <div className="md-filter-bar cm-erd__filters">
      <md-outlined-button type="button" aria-controls="cm-erd-filters" aria-expanded={open ? "true" : "false"} data-open={open ? "" : undefined} onClick={toggle}>
        <md-icon slot="icon">tune</md-icon>Bộ lọc{chips.length ? ` · ${chips.length}` : ""}
      </md-outlined-button>
      <md-chip-set class="md-filter-bar__chips">
        {chips.map(([key, label]) => <InputChip key={key} label={label}
          onRemove={() => onApply({ ...params, [key]: defaults[key] })} />)}
      </md-chip-set>
      {summary ? <span className="md-filter-bar__summary">{summary}</span> : null}
    </div>
    {open ? <section className="md-filter-panel cm-erd__panel" id="cm-erd-filters" aria-label="Bộ lọc">
      <div className="md-filter-panel__grid">
        <div><h3>Schema</h3>
          <Select className="cm-erd__schema" label="Schema" value={draft.schema || ANY_SCHEMA} options={schemaOptions}
            onChange={(value) => setDraft({ ...draft, schema: value === ANY_SCHEMA ? "" : value })} /></div>
        <div><h3>Độ sâu quanh bảng</h3>
          <Segmented label="Độ sâu" options={DEPTH_OPTIONS} value={draft.depth} onChange={(value) => setDraft({ ...draft, depth: value })} /></div>
        <div><h3>Tên hiển thị</h3>
          <Segmented label="Tên hiển thị" options={NAME_OPTIONS} value={draft.names} onChange={(value) => setDraft({ ...draft, names: value })} /></div>
        <div><h3>Cột</h3>
          <Segmented label="Cột" options={COLUMN_OPTIONS} value={draft.cols} onChange={(value) => setDraft({ ...draft, cols: value })} /></div>
      </div>
      <div className="md-filter-panel__actions">
        <Button onClick={() => setDraft({ ...params, ...defaults, table: params.table })}>Đặt lại</Button>
        <Button variant="filled" onClick={apply}>Áp dụng</Button>
      </div>
    </section> : null}
  </>;
}

// ── Page ────────────────────────────────────────────────────────────────────────────────────────────

export default function ErdPage({ params: rawParams, onOpenNode, notify }) {
  const params = erdParams(rawParams);
  const { table, schema, system, depth, names, cols } = params;
  const [catalog, setCatalog] = useState(null);
  const [model, setModel] = useState(null);
  const [state, setState] = useState({ loading: false, error: "" });
  const [dialog, setDialog] = useState(null);
  const fitRef = useRef(null);
  const abortRef = useRef(null);
  const request = useMemo(() => ({ table, schema, system, depth: table ? depth : "", keys: cols === "keys" ? "1" : "" }), [table, schema, system, depth, cols]);
  const scoped = Boolean(table || schema || system);

  useEffect(() => {
    erdApi.tables("", "").then(setCatalog).catch((reason) => setCatalog({ schemas: [], error: reason.message }));
  }, []);

  useEffect(() => {
    if (!scoped) { setModel(null); setState({ loading: false, error: "" }); return undefined; }
    if (abortRef.current) abortRef.current.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    setState({ loading: true, error: "" });
    erdApi.model({ table, schema, system, depth: table ? depth : "" }, controller.signal)
      .then((body) => { setModel(body); setState({ loading: false, error: "" }); })
      .catch((reason) => { if (reason.name !== "AbortError") { setModel(null); setState({ loading: false, error: reason.message }); } });
    return () => controller.abort();
  }, [table, schema, system, depth, scoped]);

  const handleCancel = () => {
    if (abortRef.current) abortRef.current.abort();
    setState({ loading: false, error: "" });
  };

  const go = (next) => { window.location.hash = erdHash({ ...params, ...next }); };
  const focus = (id) => { if (id && id !== model?.focus) go({ table: id, schema: "", system: "" }); };
  // Stable for the canvas (a new function would rebuild every node); always calls the latest prop.
  const openRef = useRef(onOpenNode);
  openRef.current = onOpenNode;
  const openNode = useCallback((id) => openRef.current(id), []);
  const noFk = (model && !model.has_fk_data) || (!scoped && catalog && catalog.has_fk_data === false);
  const summary = model ? `${model.tables.length} bảng · ${model.relations.length} khoá ngoại` : "";

  return <div className="cm-erd">
    <div className="cm-erd__bar">
      <div className="cm-erd__title"><md-icon>schema</md-icon><h1>ERD</h1></div>
      <TablePicker schema={schema} onPick={(id) => go({ table: id, schema: "", system: "" })} />
      <div className="cm-erd__actions">
        <Button variant="tonal" icon="account_tree" disabled={!model} onClick={() => setDialog("mermaid")}>Xuất Mermaid</Button>
        <Button variant="tonal" icon="database" disabled={!model} onClick={() => setDialog("dbml")}>Xuất DBML</Button>
        <IconButton icon="fit_screen" label="Vừa khung" disabled={!model} onClick={() => fitRef.current?.()} />
      </div>
    </div>
    <div className="cm-erd__filterline">
      <ErdFilters key={`${table}|${schema}|${depth}|${names}|${cols}`} params={params} schemas={catalog?.schemas || []} summary={summary} onApply={go} />
    </div>
    {state.loading ? (
      <div style={{ display: "flex", alignItems: "center", gap: 12, padding: "8px 16px" }}>
        <Progress style={{ flex: 1 }} />
        <Button variant="text" icon="close" onClick={handleCancel}>Huỷ</Button>
      </div>
    ) : null}
    <div className="cm-erd__notes">
      {state.error ? <ErrorBanner>{state.error}</ErrorBanner> : null}
      {noFk ? <div className="md-banner cm-erd__banner" role="status"><md-icon>info</md-icon>
        <div className="md-banner__text"><b>Chưa có dữ liệu khoá ngoại — cần extract lại bằng code-map mới.</b> Pack này được extract bằng
          bản code-map cũ nên chỉ có bảng và cột; sơ đồ chưa vẽ được quan hệ giữa các bảng.</div></div> : null}
      {model?.truncated ? <div className="md-banner cm-erd__banner" role="status"><md-icon>filter_alt</md-icon>
        <div className="md-banner__text">Chỉ hiện {model.limit} bảng; {model.omitted} bảng khác bị ẩn. Chọn một bảng và độ sâu 1 để thu hẹp.</div></div> : null}
      {model?.outside_relations ? <p className="md-muted cm-small cm-erd__outside">{model.outside_relations} khoá ngoại nối tới bảng ngoài sơ đồ này (bấm vào một bảng để xem quanh bảng đó).</p> : null}
    </div>
    <div className="cm-erd__stage">
      {model ? <ErdCanvas model={model} names={names} keysOnly={cols === "keys"} onFocus={focus} onOpenNode={openNode} fitRef={fitRef} />
        : !scoped ? <div className="cm-erd__empty">
          <Empty icon="schema" title="Chọn một bảng để xem ERD">
            Gõ tên bảng (tên kỹ thuật hoặc tên logic tiếng Nhật / tiếng Anh) vào ô phía trên. Sơ đồ hiện các bảng nối với bảng đó qua
            khoá ngoại; bấm vào một bảng trong sơ đồ để chuyển tâm sang bảng đó.
          </Empty>
          {catalog?.schemas?.length ? <div className="cm-erd__schemas">
            <span className="cm-label">Hoặc mở cả một schema</span>
            <md-chip-set>{catalog.schemas.map((item) => <md-assist-chip key={item.id} label={`${item.id} · ${item.tables} bảng`}
              onClick={() => go({ table: "", schema: item.id, system: "" })}><md-icon slot="icon">folder_data</md-icon></md-assist-chip>)}</md-chip-set>
          </div> : null}
        </div> : null}
    </div>
    {dialog && model ? <ExportDialog format={dialog} request={request} scope={model.scope} notify={notify} onClose={() => setDialog(null)} /> : null}
  </div>;
}
