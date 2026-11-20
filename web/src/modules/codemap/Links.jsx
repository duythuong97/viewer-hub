// Hand-made links between nodes (kn.biz_links).
import React, { useEffect, useState } from "react";
import { businessApi } from "./api.js";
import { Button, Dialog, ErrorBanner, IconButton, Loading, Segmented, Select, TextField } from "../../md/react.jsx";
import { typeLabel } from "./lib/text.js";

const TYPE_LABELS = {
  CALLS: "gọi (CALLS)", CALLS_API: "gọi API (CALLS_API)", HANDLED_BY: "được xử lý bởi (HANDLED_BY)", TRIGGERS: "kích hoạt (TRIGGERS)",
  TRIGGERS_JOB: "chạy job (TRIGGERS_JOB)", PUBLISHES: "gửi message (PUBLISHES)", CONSUMED_BY: "message được nhận bởi (CONSUMED_BY)",
  RENDERS: "hiển thị component (RENDERS)", READS: "đọc bảng (READS)", INSERTS: "thêm vào bảng (INSERTS)", UPDATES: "cập nhật bảng (UPDATES)",
  DELETES: "xoá khỏi bảng (DELETES)", MERGES: "merge vào bảng (MERGES)",
};
const DATA_NODE_TYPES = new Set(["TABLE", "VIEW", "MATERIALIZED_VIEW", "EXTERNAL_DATABASE_OBJECT", "SEQUENCE", "DATA_FILE", "COLUMN"]);

function useDebounced(value, delay) {
  const [current, setCurrent] = useState(value);
  useEffect(() => { const timer = setTimeout(() => setCurrent(value), delay); return () => clearTimeout(timer); }, [value, delay]);
  return current;
}

/** Add a link from (or to) `node`: pick the other node among the flow's nodes or anywhere in the graph. */
export function LinkDialog({ node, flowNodes = [], onClose, onSaved, notify, initialNote = "", gapId = "", initialType = "" }) {
  const [direction, setDirection] = useState("out");
  const [types, setTypes] = useState({ calls: ["CALLS"], data: [] });
  const [edgeType, setEdgeType] = useState(initialType || "CALLS");
  const [query, setQuery] = useState("");
  const [remote, setRemote] = useState([]);
  const [searching, setSearching] = useState(false);
  const [other, setOther] = useState(null);
  const [note, setNote] = useState(initialNote);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const typed = useDebounced(query.trim(), 250);

  useEffect(() => { businessApi.links({ node: "-" }).then((body) => setTypes(body.types)).catch(() => {}); }, []);
  useEffect(() => {
    if (typed.length < 2) { setRemote([]); return undefined; }
    const controller = new AbortController();
    setSearching(true);
    businessApi.search(typed, controller.signal)
      .then((body) => setRemote((body.nodes || []).map((hit) => ({ node_id: hit.id, name: hit.label, node_type: hit.node_type, path: hit.path }))))
      .catch(() => {}).finally(() => setSearching(false));
    return () => controller.abort();
  }, [typed]);

  const needle = query.trim().toLowerCase();
  const local = flowNodes.filter((candidate) => candidate.node_id !== node.node_id && (!needle || `${candidate.name} ${candidate.node_type}`.toLowerCase().includes(needle))).slice(0, 30);
  const seen = new Set(local.map((candidate) => candidate.node_id));
  const results = [...local.map((candidate) => ({ ...candidate, inFlow: true })), ...remote.filter((hit) => hit.node_id !== node.node_id && !seen.has(hit.node_id))];
  const source = direction === "out" ? node : other;
  const target = direction === "out" ? other : node;
  const dataType = types.data.includes(edgeType);
  const targetIsData = target ? DATA_NODE_TYPES.has(target.node_type) : true;
  const problem = !other ? "Chọn node ở danh sách bên dưới" : dataType && !targetIsData ? `${edgeType} chỉ nối tới bảng / view` : "";

  async function save(close) {
    setBusy(true); setError("");
    try {
      // A link made from the "Chỗ hở" page names its gap, so the gap leaves the list (business/gaps.py).
      const mark = gapId ? `[gap ${gapId}]` : "";
      const text = mark && !note.includes(mark) ? [note.trim(), mark].filter(Boolean).join(" · ") : note;
      const result = await businessApi.createLink({ source: source.node_id, target: target.node_id, edge_type: edgeType, note: text });
      notify("Đã thêm liên kết");
      onSaved?.(result);
      close();
    } catch (reason) {
      setError(reason.message);
    } finally {
      setBusy(false);
    }
  }

  const options = [...types.calls, ...types.data].map((type) => [type, TYPE_LABELS[type] || type]);
  const actions = (close) => <>
    <Button onClick={close}>Huỷ</Button>
    <Button variant="filled" icon="add_link" disabled={busy || Boolean(problem)} onClick={() => save(close)}>Thêm liên kết</Button>
  </>;
  return <Dialog headline="Thêm liên kết" icon="add_link" onClose={onClose} actions={actions} wide>
    <p className="md-muted cm-small">Dùng khi extract bỏ sót một lời gọi (gọi qua tên động, job chạy theo cấu hình, helper parser không theo được…). Liên kết được đi qua như cạnh thật: luồng, file xuất cho AI và MCP đều thấy, và được đánh dấu là liên kết tay.</p>
    <Segmented label="Chiều" value={direction} onChange={setDirection}
      options={[["out", "Node này → node khác", "arrow_forward"], ["in", "Node khác → node này", "arrow_back"]]} />
    <div className="cm-link-preview">
      <span className={`cm-link-end${source ? "" : " is-empty"}`}>{source ? <><small>{typeLabel(source.node_type)}</small><b>{source.name}</b></> : "Chọn node nguồn"}</span>
      <md-icon>arrow_forward</md-icon>
      <Select label="Loại cạnh" value={edgeType} onChange={setEdgeType} options={options} className="cm-link-type" />
      <md-icon>arrow_forward</md-icon>
      <span className={`cm-link-end${target ? "" : " is-empty"}`}>{target ? <><small>{typeLabel(target.node_type)}</small><b>{target.name}</b></> : "Chọn node đích"}</span>
    </div>
    <TextField label={direction === "out" ? "Tìm node đích" : "Tìm node nguồn"} leadingIcon="search" value={query} onChange={setQuery}
      supportingText="Gõ tên (ít nhất 2 ký tự) để tìm trong toàn graph; node của luồng này hiện trước." />
    <div className="cm-link-results" role="listbox" aria-label="Kết quả">
      {results.map((hit) => <button key={hit.node_id} type="button" role="option" aria-selected={other?.node_id === hit.node_id}
        className={`cm-link-hit${other?.node_id === hit.node_id ? " is-on" : ""}`} onClick={() => setOther(hit)}>
        <span className="cm-hit__type">{(hit.node_type || "").slice(0, 2)}</span>
        <span className="cm-hit__text"><b className="cm-mono">{hit.name}</b>
          <small>{[typeLabel(hit.node_type), hit.inFlow ? "trong luồng này" : hit.path || ""].filter(Boolean).join(" · ")}</small></span>
      </button>)}
      {searching || query.trim() !== typed ? <Loading inline>Đang tìm…</Loading> : null}
      {!results.length && !searching && query.trim() === typed ? <p className="md-muted cm-small">{needle.length >= 2 ? "Không thấy node nào." : "Gõ để tìm node."}</p> : null}
    </div>
    <TextField label="Ghi chú (vì sao có liên kết này)" value={note} onChange={setNote} maxLength={2000}
      supportingText="Vd: gọi qua reflection theo cấu hình JOB_CONFIG.HANDLER; xem OrderJob.cs:120" />
    {problem && other ? <p className="cm-error-text">{problem}</p> : null}
    {error ? <ErrorBanner>{error}</ErrorBanner> : null}
  </Dialog>;
}

/** One link: endpoints, type, note, who added it (a person or AI), and delete. Every link is in use. */
export function LinkRow({ link, onChanged, onOpenNode, notify, compact }) {
  const [busy, setBusy] = useState(false);
  async function act(promise, message) {
    setBusy(true);
    try { await promise; notify(message); onChanged?.(); } catch (reason) { notify(reason.message); } finally { setBusy(false); }
  }
  const end = (side) => onOpenNode && !side.missing
    ? <button type="button" className="cm-ref" title={side.address || side.node_id} onClick={() => onOpenNode(side.node_id)}>{side.ref || side.node_id}</button>
    : <code title={side.address || side.node_id}>{side.ref || side.node_id}</code>;
  const sides = [["source", "nguồn"], ["target", "đích"]];
  const moved = sides.filter(([key]) => link[key]?.moved);
  return <div className={`cm-link-row${link.origin === "ai" ? " is-ai" : ""}`}>
    <div className="cm-link-row__edge">{end(link.source)}<span className="cm-link-row__type">{link.edge_type}</span>{end(link.target)}</div>
    {link.note ? <p className="cm-small">{link.note}</p> : null}
    {moved.length ? <div className="cm-link-row__notice">
      <md-icon>sync_problem</md-icon>
      <span className="cm-small">Code đã đổi, đã gắn lại theo tên: {moved.map(([key, label]) => link[key].moved.old_ref === link[key].address
        ? <span key={key}>node {label} vẫn tên cũ, chỉ dời chỗ trong code. </span>
        : <span key={key}>node {label} trước là <code>{link[key].moved.old_ref}</code>, nay là <code>{link[key].address}</code> ({link[key].moved.reason}). </span>)}</span>
      <Button icon="check" disabled={busy} onClick={() => act(businessApi.updateLink(link.link_id, { confirm: true }), "Đã xác nhận liên kết")}>Vẫn đúng</Button>
    </div> : null}
    {sides.filter(([key]) => link[key]?.missing).map(([key, label]) => <div key={key} className="cm-link-row__notice">
      <md-icon>link_off</md-icon>
      <span className="cm-small">Node {label} không còn trong graph.{link[key].candidates?.length ? " Có thể là:" : " Không tìm thấy node nào cùng tên: chọn lại bằng cách thêm liên kết mới, hoặc xoá."}</span>
      {(link[key].candidates || []).map((candidate) => <Button key={candidate.node_id} icon="link" disabled={busy} title={candidate.reason}
        onClick={() => act(businessApi.updateLink(link.link_id, { [key]: candidate.node_id }), "Đã gắn lại liên kết")}>{candidate.address}</Button>)}
    </div>)}
    <div className="cm-link-row__foot">
      <span className="md-muted cm-small">{link.origin === "ai" ? "AI thêm" : `Liên kết tay${link.created_by ? ` · ${link.created_by}` : ""}`}
        {link.source?.missing || link.target?.missing ? " · node không còn trong graph" : ""}</span>
      <span className="md-row">
        {compact ? <IconButton icon="delete" label="Xoá liên kết" disabled={busy} onClick={() => act(businessApi.deleteLink(link.link_id), "Đã xoá liên kết")} />
          : <Button icon="delete" disabled={busy} onClick={() => act(businessApi.deleteLink(link.link_id), "Đã xoá liên kết")}>Xoá</Button>}
      </span>
    </div>
  </div>;
}

/** Links touching one node (shown in the flow's node card). */
export function NodeLinks({ nodeId, version, onChanged, notify }) {
  const [links, setLinks] = useState(null);
  const [tick, setTick] = useState(0);
  useEffect(() => {
    let live = true;
    businessApi.links({ node: nodeId }).then((body) => { if (live) setLinks(body.links); }).catch(() => { if (live) setLinks([]); });
    return () => { live = false; };
  }, [nodeId, version, tick]);
  if (!links?.length) return null;
  return <div className="cm-mentions"><span className="cm-label">Liên kết tay ({links.length})</span>
    {links.map((link) => <LinkRow key={link.link_id} link={link} compact notify={notify} onChanged={() => { setTick((value) => value + 1); onChanged?.(); }} />)}
  </div>;
}
