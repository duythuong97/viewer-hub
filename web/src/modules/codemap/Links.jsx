// Hand-made links between nodes (kn.biz_links) and sharing a pack's knowledge as one file.
import React, { useEffect, useRef, useState } from "react";
import { businessApi, currentUser } from "./api.js";
import { Button, Dialog, ErrorBanner, IconButton, Loading, Segmented, Select, TextField } from "../../md/react.jsx";
import { typeLabel } from "./lib/text.js";
import { downloadText } from "./common.jsx";

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
export function LinkDialog({ node, flowNodes = [], onClose, onSaved, notify }) {
  const [direction, setDirection] = useState("out");
  const [types, setTypes] = useState({ calls: ["CALLS"], data: [] });
  const [edgeType, setEdgeType] = useState("CALLS");
  const [query, setQuery] = useState("");
  const [remote, setRemote] = useState([]);
  const [searching, setSearching] = useState(false);
  const [other, setOther] = useState(null);
  const [note, setNote] = useState("");
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
      const result = await businessApi.createLink({ source: source.node_id, target: target.node_id, edge_type: edgeType, note });
      notify(currentUser() ? "Đã thêm liên kết" : "Đã thêm liên kết. Nhập tên ở góc phải để ghi người tạo.");
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
      {searching || query.trim() !== typed ? <Loading>Đang tìm…</Loading> : null}
      {!results.length && !searching && query.trim() === typed ? <p className="md-muted cm-small">{needle.length >= 2 ? "Không thấy node nào." : "Gõ để tìm node."}</p> : null}
    </div>
    <TextField label="Ghi chú (vì sao có liên kết này)" value={note} onChange={setNote} maxLength={2000}
      supportingText="Vd: gọi qua reflection theo cấu hình JOB_CONFIG.HANDLER; xem OrderJob.cs:120" />
    {problem && other ? <p className="cm-error-text">{problem}</p> : null}
    {error ? <ErrorBanner>{error}</ErrorBanner> : null}
  </Dialog>;
}

/** One link: endpoints, type, note, who, and approve / delete. */
export function LinkRow({ link, onChanged, onOpenNode, notify, compact }) {
  const [busy, setBusy] = useState(false);
  async function act(promise, message) {
    setBusy(true);
    try { await promise; notify(message); onChanged?.(); } catch (reason) { notify(reason.message); } finally { setBusy(false); }
  }
  const end = (side) => onOpenNode
    ? <button type="button" className="cm-ref" title={side.node_id} onClick={() => onOpenNode(side.node_id)}>{side.ref || side.node_id}</button>
    : <code title={side.node_id}>{side.ref || side.node_id}</code>;
  return <div className={`cm-link-row${link.status === "proposed" ? " is-proposed" : ""}`}>
    <div className="cm-link-row__edge">{end(link.source)}<span className="cm-link-row__type">{link.edge_type}</span>{end(link.target)}</div>
    {link.note ? <p className="cm-small">{link.note}</p> : null}
    <div className="cm-link-row__foot">
      <span className="md-muted cm-small">{link.status === "proposed" ? `${link.origin === "ai" ? "AI" : link.created_by || "Ai đó"} đề xuất · chưa dùng` : `Liên kết tay${link.created_by ? ` · ${link.created_by}` : ""}`}
        {link.source?.missing || link.target?.missing ? " · node không còn trong graph" : ""}</span>
      <span className="md-row">
        {link.status === "proposed" ? <Button icon="check" disabled={busy} onClick={() => act(businessApi.updateLink(link.link_id, { status: "approved" }), "Đã duyệt liên kết")}>Duyệt</Button> : null}
        {compact ? <IconButton icon="delete" label="Xoá liên kết" disabled={busy} onClick={() => act(businessApi.deleteLink(link.link_id), "Đã xoá liên kết")} />
          : <Button icon="delete" disabled={busy} onClick={() => act(businessApi.deleteLink(link.link_id), "Đã xoá liên kết")}>{link.status === "proposed" ? "Bỏ" : "Xoá"}</Button>}
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

const MODES = [
  ["newer", "Lấy bản sửa sau cùng", "Dòng nào hai bên đều có mà khác nhau: bản nào sửa sau thì giữ bản đó."],
  ["mine", "Giữ của tôi", "Chỉ thêm những gì tôi chưa có; không đổi gì tôi đã có."],
  ["theirs", "Lấy theo file", "Dòng nào khác nhau thì lấy theo file."],
];

/** Export this pack's knowledge to a file, or merge someone's file into it. */
export function KnowledgeShare({ notify, onImported }) {
  const [data, setData] = useState(null);
  const [fileName, setFileName] = useState("");
  const [mode, setMode] = useState("newer");
  const [check, setCheck] = useState(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const input = useRef(null);

  useEffect(() => {
    if (!data) return undefined;
    let live = true;
    setBusy(true); setError("");
    businessApi.checkKnowledge(data, mode).then((body) => { if (live) setCheck(body); })
      .catch((reason) => { if (live) { setError(reason.message); setCheck(null); } })
      .finally(() => { if (live) setBusy(false); });
    return () => { live = false; };
  }, [data, mode]);

  function readFile(file) {
    if (!file) return;
    setFileName(file.name); setCheck(null); setError("");
    const reader = new FileReader();
    reader.onload = () => {
      try { setData(JSON.parse(String(reader.result))); } catch { setData(null); setError("File không phải JSON hợp lệ"); }
    };
    reader.readAsText(file);
  }

  async function exportFile() {
    setBusy(true); setError("");
    try {
      // fetch (not a plain link) so the file records who exported it (X-Code-Map-User).
      const user = currentUser();
      const response = await fetch(businessApi.knowledgeExportUrl(), { headers: user ? { "X-Code-Map-User": encodeURIComponent(user) } : {} });
      if (!response.ok) throw new Error((await response.json().catch(() => ({}))).error?.message || `Request failed (${response.status})`);
      const name = /filename="([^"]+)"/.exec(response.headers.get("Content-Disposition") || "")?.[1] || "codemap.codemap-knowledge.json";
      downloadText(name, await response.text());
      notify("Đã tải file knowledge");
    } catch (reason) {
      setError(reason.message);
    } finally {
      setBusy(false);
    }
  }

  async function apply() {
    setBusy(true); setError("");
    try {
      const result = await businessApi.importKnowledge(data, mode);
      notify(`Đã nhập ${result.writes} mục. Bản sao lưu: ${result.backup}`);
      setData(null); setCheck(null); setFileName("");
      if (input.current) input.current.value = "";
      onImported?.(result);
    } catch (reason) {
      setError(reason.message);
    } finally {
      setBusy(false);
    }
  }

  const rows = check ? Object.entries(check.tables).filter(([, stats]) => stats.new + stats.changed + stats.same + stats.invalid > 0) : [];
  return <section className="cm-kn__section"><h2><md-icon>share</md-icon>Chia sẻ knowledge</h2>
    <p className="md-muted cm-small">Mọi thứ bạn đã viết cho pack này (tên và mô tả tính năng, tài liệu luồng, quy tắc, quyết định, câu hỏi, ghi chú, gán thuật ngữ, liên kết tay) trong một file <code>.codemap-knowledge.json</code>. Người nhận mở Code map của cùng pack và nhập file ở đây; không gì của họ bị xoá.</p>
    <div className="md-row">
      <Button variant="tonal" icon="download" disabled={busy} onClick={exportFile}>Xuất file knowledge</Button>
      <Button variant="outlined" icon="upload_file" onClick={() => input.current?.click()}>Chọn file để nhập</Button>
      <input ref={input} type="file" accept=".json,application/json" hidden onChange={(event) => readFile(event.target.files[0])} />
      {fileName ? <span className="md-muted cm-small">{fileName}</span> : null}
    </div>
    {data ? <>
      <Segmented label="Khi hai bên khác nhau" value={mode} onChange={setMode} options={MODES.map(([value, label]) => [value, label])} />
      <p className="md-muted cm-small">{MODES.find(([value]) => value === mode)[2]} Trước khi nhập, knowledge hiện tại được sao lưu.</p>
    </> : null}
    {busy ? <md-linear-progress indeterminate /> : null}
    {error ? <ErrorBanner>{error}</ErrorBanner> : null}
    {check ? <>
      <p className="cm-small">File của <b>{check.from.exported_by || "không rõ"}</b>{check.from.exported_at ? ` · xuất lúc ${check.from.exported_at}` : ""}{check.from.pack?.id ? ` · pack ${check.from.pack.id} ${check.from.pack.version || ""}` : ""}</p>
      {check.warnings.map((warning) => <p key={warning} className="cm-error-text">{warning}</p>)}
      <div className="md-table-wrap"><table className="md-table"><thead><tr><th>Loại</th><th className="md-table__num">Mới</th><th className="md-table__num">Giống</th>
        <th className="md-table__num">Khác nhau</th><th className="md-table__num">Sẽ lấy theo file</th><th className="md-table__num">Giữ của tôi</th></tr></thead>
        <tbody>{rows.map(([name, stats]) => <tr key={name}><td>{stats.label}{stats.examples.length ? <details className="cm-kn__details"><summary>Ví dụ khác nhau</summary>
          <ul>{stats.examples.map((example, index) => <li key={index}>{example.name || "(không tên)"} · của tôi {example.mine || "?"} · file {example.theirs || "?"} → {example.take ? "lấy theo file" : "giữ của tôi"}</li>)}</ul></details> : null}</td>
          <td className="md-table__num">{stats.new}</td><td className="md-table__num">{stats.same}</td><td className="md-table__num">{stats.changed}</td>
          <td className="md-table__num">{stats.take}</td><td className="md-table__num">{stats.keep}</td></tr>)}</tbody></table></div>
      <div className="md-row"><Button variant="filled" icon="merge" disabled={busy || !check.ok} onClick={apply}>{check.ok ? `Nhập ${check.writes} mục` : "Không có gì mới"}</Button></div>
    </> : null}
  </section>;
}
