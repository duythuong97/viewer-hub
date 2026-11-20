import React, { useEffect, useMemo, useRef, useState } from "react";
import { businessApi } from "./api.js";
import { config } from "./config.js";
import FlowGraph from "./graph/FlowGraph.jsx";
import Swimlane from "./graph/Swimlane.jsx";
import { Button, ErrorBanner, IconButton, Loading, Segmented, Select, TextField } from "../../md/react.jsx";
import { Inline, Kind, NodeRef, RichText, RuleStatus, Status } from "./common.jsx";
import { citedNames, flowParts, nodeLookup, partCounts, typeLabel } from "./lib/text.js";
import { LinkDialog, NodeLinks } from "./Links.jsx";
import { FlowDataView, FlowTables, NAME_OPTIONS, erdLink, useErdNames, useFlowData } from "./FlowData.jsx";

function readDocOpen() {
  try { return localStorage.getItem("viewer-hub.codemap.doc") !== "0"; } catch { return true; }
}

// The stage answers one question at a time (docs/solutions/codemap-redesign-solution.md §4): how the flow runs, what
// data it touches (the ERD of its tables), what it depends on. Level of detail and Graph / Swimlane are options of the
// graph views, not separate bars.
const VIEWS = [["run", "Luồng chạy", "play_arrow"], ["data", "Dữ liệu", "database"], ["deps", "Phụ thuộc", "account_tree"]];
const VIEW_KEY = "viewer-hub.codemap.view";
const LEVELS = [["SYSTEM", "Hệ thống"], ["APPLICATION", "Ứng dụng"], ["TECHNICAL", "Kỹ thuật"]];
const DRAWINGS = [["graph", "Graph"], ["lane", "Swimlane"]];
function readView() {
  try { const value = localStorage.getItem(VIEW_KEY); return VIEWS.some(([key]) => key === value) ? value : "run"; } catch { return "run"; }
}

export default function FlowView({ flowId, onTree, onOpenItem, onOpenNode, onExport, onImport, onSnippet, notify }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  const [activeStep, setActiveStep] = useState(null);
  const [selected, setSelected] = useState(null);
  const [mode, setMode] = useState("graph");
  const [editing, setEditing] = useState(null);
  const [draft, setDraft] = useState(null);
  const [picking, setPicking] = useState(false);
  const [docOpen, setDocOpen] = useState(readDocOpen);
  const [linking, setLinking] = useState(null);
  const [version, setVersion] = useState(0);
  const [shown, setShown] = useState(null);
  const [view, setViewState] = useState(readView);
  const [semantic, setSemantic] = useState("TECHNICAL");
  const [dataFocus, setDataFocus] = useState("");
  const setView = (next) => { setViewState(next); try { localStorage.setItem(VIEW_KEY, next); } catch { /* ignore */ } };
  const tables = useFlowData(flowId, version);
  const [names, setNames] = useErdNames();
  const toggleDoc = (open) => { setDocOpen(open); try { localStorage.setItem("viewer-hub.codemap.doc", open ? "1" : "0"); } catch { /* ignore */ } };
  const docRef = useRef(null);

  useEffect(() => {
    let live = true;
    setData(null); setError(""); setActiveStep(null); setSelected(null); setEditing(null); setPicking(false);
    businessApi.flow(flowId).then((body) => { if (live) setData(body); }).catch((reason) => { if (live) setError(reason.message); });
    return () => { live = false; };
  }, [flowId]);

  // After a link is added or removed: the flow's nodes and edges change, the document does not.
  async function reloadGraph(tree) {
    try {
      const body = await businessApi.flow(flowId);
      setData(body);
      setVersion((value) => value + 1);
      if (tree) onTree(tree);
    } catch (reason) {
      notify(reason.message);
    }
  }

  const nodes = data?.nodes || [];
  const nodesById = useMemo(() => new Map(nodes.map((node) => [node.node_id, node])), [nodes]);
  const lookup = useMemo(() => nodeLookup(nodes), [nodes]);

  if (error) return <div className="cm-page"><ErrorBanner>{error}</ErrorBanner></div>;
  if (!data) return <Loading>Đang tải luồng…</Loading>;

  const flow = data.flow;
  const steps = flow.steps || [];
  const parts = flowParts(flow);
  const counts = partCounts(parts.map((part) => part.status));
  const editingStep = typeof editing === "string" && editing.startsWith("step:") ? steps.find((step) => `step:${step.id}` === editing) : null;
  const stepNodes = steps.map((step) => (editingStep && step.id === editingStep.id ? draft.nodes : step.nodes) || []);

  async function patch(part, body, message) {
    try {
      const result = await businessApi.updatePart(flowId, part, body);
      setData(result);
      onTree(result.tree);
      setEditing(null); setPicking(false);
      notify(message);
    } catch (reason) {
      notify(reason.message);
    }
  }

  function startEdit(part) {
    setPicking(false);
    if (part === "summary") setDraft({ name: flow.name || "", text: flow.summary?.text || "" });
    else if (part === "edge_cases") setDraft({ text: (flow.edge_cases?.items || []).join("\n\n") });
    else {
      const step = steps.find((candidate) => `step:${candidate.id}` === part);
      setDraft({ name: step.name || "", actor: step.actor || "", text: step.text || "", nodes: [...(step.nodes || [])], rules: (step.rules || []).map((rule) => ({ ...rule })) });
      setActiveStep(step.id);
    }
    setEditing(part);
  }

  function saveEdit() {
    if (editing === "summary") return patch("summary", { name: draft.name, text: draft.text }, "Đã lưu. Phần này sẽ không bị AI ghi đè.");
    if (editing === "edge_cases") return patch("edge_cases", { items: draft.text.split(/\n\s*\n/).map((value) => value.trim()).filter(Boolean) }, "Đã lưu");
    return patch(editing, { name: draft.name, actor: draft.actor, text: draft.text, nodes: draft.nodes, rules: draft.rules }, "Đã lưu. Phần này sẽ không bị AI ghi đè.");
  }

  function onNodeClick(nodeId) {
    if (picking && editingStep) {
      setDraft((current) => ({ ...current, nodes: current.nodes.includes(nodeId) ? current.nodes.filter((id) => id !== nodeId) : [...current.nodes, nodeId] }));
      return;
    }
    setSelected((current) => (current === nodeId ? null : nodeId));
    const ref = docRef.current?.querySelector(`.cm-step .cm-prose .cm-ref[data-node="${CSS.escape(nodeId)}"]`)
      || docRef.current?.querySelector(`.cm-ref[data-node="${CSS.escape(nodeId)}"]`);
    ref?.scrollIntoView({ block: "center", behavior: "smooth" });
  }

  function cite(nodeId) {
    setSelected(nodeId);
    setMode("graph");
    if (view === "data") setView("run");
  }

  function showTable(tableId) {
    setDataFocus(tableId);
    setView("data");
  }

  // Picking a step's nodes needs the graph; Swimlane is a drawing of how the flow runs only.
  const shownView = picking ? "run" : view;
  const drawing = shownView === "run" ? mode : "graph";
  const scrollTo = (id) => docRef.current?.querySelector(`#${id}`)?.scrollIntoView({ block: "start", behavior: "smooth" });
  // A part whose code changed since it was saved: "Vẫn đúng" saves it unchanged, measured against the code as it is now.
  const unchanged = (part) => part === "summary" ? { text: flow.summary?.text || "" }
    : part === "edge_cases" ? { items: flow.edge_cases?.items || [] }
      : { text: steps.find((step) => `step:${step.id}` === part)?.text || "" };
  const tools = (part, changed) => editing === part ? null : <span className="cm-step__tools">
    <Button icon="edit" onClick={(event) => { event.stopPropagation(); startEdit(part); }}>Sửa</Button>
    {changed ? <Button icon="task_alt" onClick={(event) => { event.stopPropagation(); patch(part, unchanged(part), "Đã ghi nhận: vẫn đúng với code hiện tại"); }}>Vẫn đúng</Button> : null}
  </span>;

  return <div className={`cm-flow${docOpen ? "" : " cm-flow--doc-closed"}`}>
    <article className="cm-doc" ref={docRef} hidden={!docOpen}>
      <nav className="cm-toc" aria-label="Mục lục">
        <IconButton icon="left_panel_close" label="Thu gọn tài liệu" onClick={() => toggleDoc(false)} />
        <button type="button" className="cm-toc__item" onClick={() => scrollTo("cm-sec-summary")}>Tổng quan</button>
        <button type="button" className="cm-toc__item" onClick={() => scrollTo("cm-sec-steps")}>Các bước <span className="md-badge">{steps.length}</span></button>
        <button type="button" className="cm-toc__item" onClick={() => scrollTo("cm-sec-data")}>Dữ liệu{tables.data ? <span className="md-badge">{tables.data.tables.length}</span> : null}</button>
        <button type="button" className="cm-toc__item" onClick={() => scrollTo("cm-sec-edge")}>Ngoại lệ</button>
      </nav>
      <div className="cm-doc__in">
        <header className="cm-doc__head" id="cm-sec-summary">
          <div className="cm-crumbs">{(data.path || []).slice(0, -1).map((step) => <React.Fragment key={step.id}>
            <button type="button" className="cm-link" onClick={() => onOpenItem(step)}>{step.name}</button><md-icon>chevron_right</md-icon></React.Fragment>)}<span>{flow.name}</span></div>
          <h1>{flow.name || "Luồng chưa đặt tên"}</h1>
          <div className="cm-doc__meta">
            {data.has_doc ? <span className="cm-review"><span className="cm-review__bar"><i style={{ width: `${(counts.person / Math.max(counts.total, 1)) * 100}%` }} className="cm-review--edited" /></span>
              {counts.person}/{counts.total} phần do người viết</span> : null}
            {flow.imported_at ? <span>AI viết · nhập lúc {flow.imported_at}</span> : data.has_doc ? <span>Viết tay</span> : <span>Chưa có tài liệu · các bước đã được tách từ graph. Xuất tính năng cho AI để viết.</span>}
          </div>
          <div className="md-row">
            <Button variant="tonal" icon="download" onClick={() => onExport(data.feature_id)}>Xuất cho AI</Button>
            <Button variant="outlined" icon="upload" onClick={() => onImport(data.feature_id)}>Nhập kết quả AI</Button>
          </div>
        </header>

        <section className="cm-block">
          <div className="cm-block__h"><h2>Tổng quan</h2>{flow.summary?.text ? <Status status={flow.summary.status} by={flow.summary.reviewed_by} changed={flow.summary.code_changed} /> : null}{tools("summary", flow.summary?.code_changed)}</div>
          {editing === "summary" ? <div className="cm-edit">
            <TextField label="Tên luồng" value={draft.name} onChange={(name) => setDraft({ ...draft, name })} />
            <TextField label="Tóm tắt" type="textarea" rows={7} value={draft.text} onChange={(text) => setDraft({ ...draft, text })}
              supportingText="Cách đoạn bằng một dòng trống. Gõ [[tên node]] để trích dẫn, **chữ** để nhấn mạnh." />
            <EditFoot onCancel={() => setEditing(null)} onSave={saveEdit} />
          </div> : flow.summary?.text ? <RichText text={flow.summary.text} lookup={lookup} selected={selected} onCite={cite} />
            : <p className="md-muted">Chưa có tóm tắt. Xuất tính năng cho AI để viết, hoặc bấm Sửa để tự viết.</p>}
          {(flow.facts || []).length ? <dl className="cm-facts">{flow.facts.map(([key, value]) => <div key={key}><dt>{key}</dt><dd>{value}</dd></div>)}</dl> : null}
        </section>

        <section className="cm-block" id="cm-sec-steps">
          <div className="cm-block__h"><h2>Các bước</h2><span className="md-muted cm-small">{steps.length} bước · tách từ graph</span></div>
          <div className="cm-timeline">
            {steps.map((step, index) => {
              const part = `step:${step.id}`;
              return <div key={step.id} id={`cm-step-${step.id}`} className={`cm-step${activeStep === step.id ? " is-active" : ""}`}>
                <span className="cm-step__num">{index + 1}</span>
                <div className="cm-step__body" onClick={(event) => { if (!event.target.closest("button, input, textarea, details, a, md-text-button, md-outlined-text-field")) setActiveStep(activeStep === step.id ? null : step.id); }}>
                  <div className="cm-step__h"><h3>{step.name || <span className="md-muted">Chưa đặt tên</span>}</h3>{tools(part, step.code_changed)}</div>
                  <div className="cm-step__sub">
                    {step.actor ? <span className="cm-actor"><md-icon>{/hệ thống|system/i.test(step.actor) ? "memory" : "person"}</md-icon>{step.actor}</span> : null}
                    {step.text ? <Status status={step.status} by={step.reviewed_by} changed={step.code_changed} /> : <span className="md-muted">Chưa viết</span>}
                  </div>
                  {editing === part ? <StepEditor draft={draft} setDraft={setDraft} picking={picking} setPicking={setPicking} nodesById={nodesById}
                    onCancel={() => { setEditing(null); setPicking(false); }} onSave={saveEdit} /> : <>
                    <RichText text={step.text} lookup={lookup} selected={selected} onCite={cite} />
                    {(step.rules || []).length ? <div className="cm-rules">{step.rules.map((rule, position) => <div key={position} className="cm-rule">
                      <b>{rule.title}</b>
                      {rule.text ? <p><Inline text={rule.text} lookup={lookup} selected={selected} onCite={cite} /></p> : null}
                      <div className="cm-rule__foot">{rule.at ? <><span>Kiểm tra tại</span><Inline text={`[[${rule.at}]]`} lookup={lookup} selected={selected} onCite={cite} /></> : null}
                        {rule.evidence ? <code className="cm-evidence">{rule.evidence}</code> : null}<RuleStatus status={rule.status} /></div>
                    </div>)}</div> : null}
                    {(step.orphans || []).length ? <p className="cm-error-text">Tham chiếu không có trong graph: {step.orphans.join(", ")}</p> : null}
                    <details className="cm-nodes"><summary><md-icon>chevron_right</md-icon>{(step.nodes || []).length} node liên quan</summary>
                      <div className="cm-node-list">{(step.nodes || []).map((id) => nodesById.get(id)).filter(Boolean).map((node) =>
                        <NodeRef key={node.node_id} id={node.node_id} name={node.name} selected={selected === node.node_id} title={`${node.node_type} · ${node.node_id}`} onClick={() => cite(node.node_id)} />)}</div>
                    </details>
                  </>}
                </div>
              </div>;
            })}
          </div>
        </section>

        <section className="cm-block" id="cm-sec-data">
          <div className="cm-block__h"><h2>Dữ liệu</h2><span className="md-muted cm-small">Bảng luồng đọc / ghi · bấm một bảng để xem trong ERD</span>
            {view !== "data" ? <span className="cm-step__tools"><Button icon="schema" onClick={() => setView("data")}>Xem ERD</Button></span> : null}</div>
          <FlowTables state={tables} onShow={showTable} />
        </section>

        <section className="cm-block" id="cm-sec-edge">
          <div className="cm-block__h"><h2>Ngoại lệ và trường hợp đặc biệt</h2>{flow.edge_cases?.items?.length ? <Status status={flow.edge_cases.status} by={flow.edge_cases.reviewed_by} changed={flow.edge_cases.code_changed} /> : null}{tools("edge_cases", flow.edge_cases?.code_changed)}</div>
          {editing === "edge_cases" ? <div className="cm-edit">
            <TextField label="Mỗi trường hợp một đoạn" type="textarea" rows={6} value={draft.text} onChange={(text) => setDraft({ ...draft, text })} />
            <EditFoot onCancel={() => setEditing(null)} onSave={saveEdit} />
          </div> : (flow.edge_cases?.items || []).length ? <ul className="cm-bullets">{flow.edge_cases.items.map((item, index) => <li key={index}><Inline text={item} lookup={lookup} selected={selected} onCite={cite} /></li>)}</ul>
            : <p className="md-muted">Chưa có.</p>}
        </section>
      </div>
    </article>

    <section className="cm-stage">
      <div className="cm-stage__bar">
        {!docOpen ? <Button variant="tonal" icon="left_panel_open" title="Tài liệu" onClick={() => toggleDoc(true)}><span className="cm-stage__label">Tài liệu</span></Button> : null}
        <Segmented dense label="Xem" value={shownView} onChange={setView} options={VIEWS} />
        <span className="md-muted cm-small cm-stage__status" title="Số node / cạnh đang vẽ">{shownView === "data"
          ? (tables.data ? `${tables.data.tables.length} bảng · ${tables.data.erd?.relations?.length || 0} khoá ngoại` : "")
          : <>{drawing === "graph" && shown && shown.level !== "TECHNICAL"
            ? `${shown.nodes} ${shown.level === "SYSTEM" ? "hệ thống" : "node"} · ${shown.edges} cạnh (của ${nodes.length} node)`
            : `${nodes.length} node · ${(data.edges || []).length} cạnh`}{(data.edges || []).some((edge) => edge.manual) ? ` (${data.edges.filter((edge) => edge.manual).length} liên kết tay)` : ""}{activeStep ? ` · đang xem bước ${steps.findIndex((step) => step.id === activeStep) + 1}` : ""}{picking ? " · nhấn node để thêm hoặc bỏ khỏi bước" : ""}</>}</span>
        {shownView !== "data" && drawing === "graph"
          ? <Select className="cm-stage__select" label="Mức chi tiết" value={semantic} onChange={setSemantic} options={LEVELS} /> : null}
        {shownView === "run" ? <Select className="cm-stage__select" label="Cách vẽ" value={mode} onChange={setMode} options={DRAWINGS} /> : null}
        {shownView === "data" ? <Select className="cm-stage__select" label="Tên hiển thị" value={names} onChange={setNames} options={NAME_OPTIONS} /> : null}
        {shownView === "data" && erdLink(tables.data)
          ? <Button variant="outlined" icon="schema" title="Mở trong ERD" onClick={() => { window.location.href = erdLink(tables.data); }}><span className="cm-stage__label">Mở trong ERD</span></Button> : null}
      </div>
      {/* The graph stays mounted in the other views so expansions, hidden edges and dragged nodes survive. */}
      <div className="cm-graph-slot" hidden={drawing !== "graph" || shownView === "data"}>
        <FlowGraph nodes={nodes} edges={data.edges || []} levels={data.levels} folded={data.folded} steps={steps} stepNodes={stepNodes} activeStep={editingStep?.id || activeStep} selected={selected}
          picking={picking} entry={data.entry_node_id || steps[0]?.nodes?.[0]} onNodeClick={onNodeClick} onShown={setShown} notify={notify}
          lens={shownView === "deps" ? "deps" : "run"} semantic={semantic} onLens={setView} />
      </div>
      {drawing === "lane" ? <Swimlane steps={steps} stepNodes={stepNodes} nodesById={nodesById} activeStep={activeStep} selected={selected} onStep={setActiveStep} onNode={onNodeClick} /> : null}
      {shownView === "data" ? <FlowDataView state={tables} names={names} focus={dataFocus} onFocus={setDataFocus} onOpenNode={onOpenNode} /> : null}
      {selected && drawing === "graph" && shownView !== "data" && !picking ? <NodeCard node={nodesById.get(selected) || { node_id: selected, name: selected, node_type: "" }} flow={flow} onOpenNode={onOpenNode}
        onSnippet={onSnippet} onClose={() => setSelected(null)} version={version} notify={notify}
        onLink={(node) => setLinking(node)} onLinksChanged={() => reloadGraph()}
        onStep={(id) => { setActiveStep(id); docRef.current?.querySelector(`#cm-step-${id}`)?.scrollIntoView({ block: "start", behavior: "smooth" }); }} /> : null}
    </section>
    {linking ? <LinkDialog node={linking} flowNodes={nodes} notify={notify} onClose={() => setLinking(null)}
      onSaved={(result) => reloadGraph(result.tree)} /> : null}
  </div>;
}

function EditFoot({ onCancel, onSave }) {
  return <div className="cm-edit__foot"><span className="md-muted cm-small">Phần đã sửa tay được khoá khi xuất cho AI.</span>
    <span className="md-row"><Button onClick={onCancel}>Huỷ</Button><Button variant="filled" icon="save" onClick={onSave}>Lưu thay đổi</Button></span></div>;
}

function StepEditor({ draft, setDraft, picking, setPicking, nodesById, onCancel, onSave }) {
  const setRule = (index, key, value) => setDraft({ ...draft, rules: draft.rules.map((rule, position) => (position === index ? { ...rule, [key]: value } : rule)) });
  return <div className="cm-edit">
    <TextField label="Tên bước" value={draft.name} onChange={(name) => setDraft({ ...draft, name })} />
    <TextField label="Người / hệ thống thực hiện" value={draft.actor} onChange={(actor) => setDraft({ ...draft, actor })} />
    <TextField label="Nội dung" type="textarea" rows={8} value={draft.text} onChange={(text) => setDraft({ ...draft, text })}
      supportingText="Cách đoạn bằng một dòng trống. Gõ [[tên node]] để trích dẫn, **chữ** để nhấn mạnh." />
    {draft.rules.map((rule, index) => <div key={index} className="cm-edit__group">
      <span className="cm-label">Quy tắc {index + 1}{rule.at ? ` · tại ${rule.at}` : ""}</span>
      <TextField label={`Tên quy tắc ${index + 1}`} value={rule.title} onChange={(value) => setRule(index, "title", value)} />
      <TextField label={`Nội dung quy tắc ${index + 1}`} type="textarea" rows={3} value={rule.text} onChange={(value) => setRule(index, "text", value)} />
    </div>)}
    <div className="cm-edit__group"><span className="cm-label">Node của bước ({draft.nodes.length})</span>
      <div className="cm-node-list">{draft.nodes.map((id) => nodesById.get(id)).filter(Boolean).map((node) => <span key={node.node_id} className="cm-ref">{node.name}</span>)}</div>
      <span><Button variant={picking ? "filled" : "outlined"} icon="ads_click" onClick={() => setPicking(!picking)}>{picking ? "Đang chọn trên graph…" : "Chọn lại node trên graph"}</Button></span>
    </div>
    <EditFoot onCancel={onCancel} onSave={onSave} />
  </div>;
}

function NodeCard({ node, flow, onClose, onStep, onOpenNode, onSnippet, onLink, onLinksChanged, version, notify }) {
  if (!node) return null;
  const mentions = [];
  (flow.steps || []).forEach((step, index) => {
    if (citedNames(step.text).some((name) => name === node.name || name === node.ref)) mentions.push([step.id, `B${index + 1} · ${step.name || "Chưa đặt tên"}`]);
    (step.rules || []).forEach((rule) => { if (rule.at === node.name || rule.at_node_id === node.node_id) mentions.push([step.id, `Quy tắc: ${rule.title}`]); });
  });
  const inSteps = (flow.steps || []).map((step, index) => ((step.nodes || []).includes(node.node_id) ? `B${index + 1}` : "")).filter(Boolean);
  return <div className="cm-pop" role="dialog" aria-label={node.name}>
    <div className="cm-pop__h"><div><Kind>{typeLabel(node.node_type)}</Kind><h4>{node.name}</h4></div>
      <IconButton icon="close" label="Đóng" onClick={onClose} /></div>
    <dl className="cm-kv">
      <dt>node_id</dt><dd><code>{node.node_id}</code></dd>
      {node.file ? <><dt>Nguồn</dt><dd><code>{node.file}{node.line ? `:${node.line}` : ""}</code></dd></> : null}
      {node.term ? <><dt>Từ điển</dt><dd>{node.term}</dd></> : null}
      {node.names?.ja || node.names?.en ? <><dt>JA / EN</dt><dd>{[node.names.ja, node.names.en].filter(Boolean).join(" · ")}</dd></> : null}
      <dt>Thuộc bước</dt><dd>{inSteps.length ? inSteps.join(", ") : "chưa thuộc bước nào"}</dd>
    </dl>
    {mentions.length ? <div className="cm-mentions"><span className="cm-label">Được nhắc trong tài liệu</span>
      {mentions.map(([stepId, label], index) => <button key={index} type="button" className="cm-mention" onClick={() => onStep(stepId)}>
        <md-icon>subdirectory_arrow_right</md-icon><span>{label}</span></button>)}</div> : null}
    <NodeLinks nodeId={node.node_id} version={version} notify={notify} onChanged={onLinksChanged} />
    <div className="md-row">
      {onOpenNode ? <Button variant="tonal" icon="hub" onClick={() => onOpenNode(node.node_id)}>Chi tiết và graph từ node này</Button> : null}
      {onLink ? <Button icon="add_link" onClick={() => onLink(node)}>Thêm liên kết</Button> : null}
      {config.source && node.file ? <Button icon="code" onClick={() => onSnippet(node.file, node.node_id)}>Xem file nguồn</Button> : null}
    </div>
  </div>;
}
