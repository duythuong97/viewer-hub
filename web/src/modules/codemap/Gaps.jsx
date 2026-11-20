// "Chỗ hở": calls, reads and writes the extract could not follow (business/gaps.py). Each gap lists the nodes it
// may mean: "Nối" adds the link (a person's link, walked at once), "Không phải" takes the gap off the list.
import React, { useCallback, useEffect, useState } from "react";
import { businessApi } from "./api.js";
import { Button, ErrorBanner, FilterBar, Loading, Select } from "../../md/react.jsx";
import { Kind } from "./common.jsx";
import { LinkDialog } from "./Links.jsx";
import { typeLabel } from "./lib/text.js";

const PAGE = 20;
const ISSUE_LABELS = {
  UNRESOLVED_REFERENCE: "Tên code gọi tới nhưng không tìm thấy",
  UNRESOLVED_CALL: "Lời gọi không xác định được đích",
  URL_DYNAMIC: "URL ghép lúc chạy",
  SQL_DYNAMIC: "SQL ghép lúc chạy",
  ROUTE_AMBIGUOUS: "URL khớp nhiều API",
  ROUTE_PREFIX_MISMATCH: "URL không khớp API nào",
  EXTRACTOR_CALL_UNBOUND: "Lời gọi parser không theo được",
  DYNAMIC_SQL: "SQL ghép lúc chạy",
  DYNAMIC_CONFIG_KEY: "Đích lấy từ cấu hình",
  DYNAMIC_URL: "URL ghép lúc chạy",
};
const issueLabel = (type) => ISSUE_LABELS[type] || (type.startsWith("DYNAMIC_") ? "Đích xác định lúc chạy" : type);

function End({ end, onOpenNode }) {
  return <button type="button" className="cm-ref" title={end.address || end.node_id} onClick={() => onOpenNode(end.node_id)}>{end.ref || end.node_id}</button>;
}

function GapCard({ gap, types, onOpenNode, onChanged, notify }) {
  const [edgeType, setEdgeType] = useState(gap.edge_type || "CALLS");
  const [busy, setBusy] = useState(false);
  const [picking, setPicking] = useState(false);
  const sources = [gap.source, ...(gap.sources || [])];
  const note = `Nối từ chỗ hở: ${gap.reference || gap.type}`;

  async function connect(target) {
    setBusy(true);
    try {
      for (const source of sources) {
        await businessApi.createLink({ source: source.node_id, target: target.node_id, edge_type: edgeType, note: `${note} · [gap ${gap.id}]` });
      }
      notify(`Đã nối tới ${target.ref || target.node_id}`);
      onChanged();
    } catch (reason) {
      notify(reason.message);
    } finally {
      setBusy(false);
    }
  }

  async function dismiss() {
    setBusy(true);
    try { await businessApi.dismissGap(gap.id); notify("Đã bỏ chỗ hở này khỏi danh sách"); onChanged(); }
    catch (reason) { notify(reason.message); } finally { setBusy(false); }
  }

  const options = [...types.calls, ...types.data].map((type) => [type, type]);
  return <article className="cm-gap">
    <header className="cm-gap__head">
      <span className="cm-status" title={gap.type}>{issueLabel(gap.type)}</span>
      {gap.reference ? <code className="cm-gap__ref">{gap.reference}</code> : null}
    </header>
    <div className="cm-gap__from cm-small"><span className="md-muted">Từ</span>
      {sources.map((end) => <End key={end.node_id} end={end} onOpenNode={onOpenNode} />)}
      {gap.more_sources ? <span className="md-muted">và {gap.more_sources} node khác</span> : null}
    </div>
    {gap.message ? <p className="md-muted cm-small cm-gap__message">{gap.message}</p> : null}
    <div className="cm-gap__candidates">
      <span className="cm-label">Có thể là</span>
      {gap.candidates?.length ? gap.candidates.map((candidate) => <div key={candidate.node_id} className="cm-gap__candidate">
        <span className="cm-hit__type">{(candidate.node_type || "").slice(0, 2)}</span>
        <span className="cm-hit__text"><b className="cm-mono" title={candidate.node_id}>{candidate.address}</b>
          <small>{[typeLabel(candidate.node_type), candidate.reason].filter(Boolean).join(" · ")}</small></span>
        <Button icon="add_link" disabled={busy} onClick={() => connect(candidate)}>Nối</Button>
      </div>) : <p className="md-muted cm-small">Không có node nào trong graph mang tên này: có thể nằm ngoài phần đã quét. Chọn node khác nếu bạn biết.</p>}
    </div>
    <footer className="md-row cm-gap__actions">
      <Select label="Loại cạnh" value={edgeType} onChange={setEdgeType} options={options} className="cm-link-type" />
      <Button icon="search" disabled={busy} onClick={() => setPicking(true)}>Chọn node khác</Button>
      <Button icon="block" disabled={busy} onClick={dismiss}>Không phải</Button>
    </footer>
    {picking ? <LinkDialog node={{ node_id: gap.source.node_id, name: gap.source.ref, node_type: gap.source.node_type }}
      initialNote={note} gapId={gap.id} initialType={edgeType} notify={notify}
      onSaved={onChanged} onClose={() => setPicking(false)} /> : null}
  </article>;
}

export default function GapsPage({ onOpenNode, notify }) {
  const [system, setSystem] = useState("");
  const [offset, setOffset] = useState(0);
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  const load = useCallback(() => {
    setError("");
    return businessApi.gaps({ system, offset, limit: PAGE }).then(setData).catch((reason) => setError(reason.message));
  }, [system, offset]);
  useEffect(() => { load(); }, [load]);

  const types = data?.types || { calls: ["CALLS"], data: [] };
  return <article className="cm-page cm-page--wide">
    <header className="cm-page__head">
      <Kind icon="link_off">Graph</Kind>
      <h1>Chỗ hở</h1>
      <p className="cm-lead">Những lời gọi, câu đọc / ghi bảng mà extract không theo được (tên ghép lúc chạy, gọi qua cấu hình, tên không có trong phần đã quét). Nối đúng node thì luồng, file xuất cho AI và MCP đi tiếp qua chỗ đó; chỗ nào không phải lời gọi thật thì bấm <b>Không phải</b>.</p>
    </header>
    <div className="cm-kn__toolbar">
      <div className="cm-kn__filters"><FilterBar panelId="cm-gap-filter" summary={data ? `${data.total} chỗ hở` : ""}
        filters={[{ key: "system", label: "Hệ thống", value: system, defaultValue: "",
          options: [["", "Mọi hệ thống"], ...(data?.systems || []).map((name) => [name.toLowerCase(), name])] }]}
        onApply={(values) => { setSystem(values.system); setOffset(0); }} /></div>
    </div>
    {error ? <ErrorBanner>{error}</ErrorBanner> : null}
    {!data && !error ? <Loading>Đang tìm chỗ hở…</Loading> : null}
    {data && !data.items.length ? <p className="md-muted">Không còn chỗ hở nào{system ? " trong hệ thống này" : ""}.</p> : null}
    {data?.items.map((gap) => <GapCard key={gap.id} gap={gap} types={types} onOpenNode={onOpenNode} onChanged={load} notify={notify} />)}
    {data && data.total > PAGE ? <div className="md-row">
      <Button icon="chevron_left" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE))}>Trước</Button>
      <span className="md-muted cm-small">{offset + 1}–{Math.min(offset + PAGE, data.total)} / {data.total}</span>
      <Button icon="chevron_right" disabled={offset + PAGE >= data.total} onClick={() => setOffset(offset + PAGE)}>Sau</Button>
    </div> : null}
  </article>;
}
