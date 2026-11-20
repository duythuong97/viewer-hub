import React, { useEffect, useMemo, useState } from "react";
import { api, businessApi } from "./api.js";
import { config } from "./config.js";
import DetailPanel from "./DetailPanel.jsx";
import FlowGraph from "./graph/FlowGraph.jsx";
import { Button, ErrorBanner, Loading } from "../../md/react.jsx";
import { Kind } from "./common.jsx";
import { NodeNotes } from "./Notes.jsx";
import { props } from "./lib/format.js";
import { typeLabel } from "./lib/text.js";

const START = [["1", "in"], ["1", "out"]];
const NO_EDGES = [];

// Source file of a node as the detail API returns it (properties or the evidence it was declared at).
function sourceOf(detail, fallback) {
  const node = detail?.node || {};
  const p = props(node);
  const path = p.source_path || p.path_in_source || node.source_path || fallback?.file || "";
  return path && !/^[a-z]+:\/\//i.test(path) ? path : "";
}

// Graph from any code node (what the old explorer did), with the explorer's detail panel beside it.
export default function NodePage({ nodeId, onOpenItem, onOpenNode, onSnippet, notify }) {
  const [page, setPage] = useState(null);
  const [error, setError] = useState("");
  const [selected, setSelected] = useState(nodeId);
  const [detail, setDetail] = useState(null);
  const [history, setHistory] = useState([]);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    let live = true;
    setPage(null); setError(""); setSelected(nodeId); setHistory([]);
    businessApi.node(nodeId).then((body) => { if (live) setPage(body); }).catch((reason) => { if (live) setError(reason.message); });
    return () => { live = false; };
  }, [nodeId]);

  useEffect(() => {
    if (!selected) return undefined;
    const controller = new AbortController();
    setLoading(true);
    api(`/detail?target_id=${encodeURIComponent(selected)}&target_type=NODE&locale=vi&relations=0`, { signal: controller.signal })
      .then((body) => setDetail(body))
      .catch((reason) => { if (reason.name !== "AbortError") setDetail({ error: reason.message }); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [selected]);

  function select(id) {
    if (!id || id === selected) return;
    setHistory((current) => [...current, selected]);
    setSelected(id);
  }

  const rootNodes = useMemo(() => (page ? [page.node] : []), [page]);

  if (error) return <div className="cm-page"><ErrorBanner>{error}</ErrorBanner></div>;
  if (!page) return <Loading />;
  const node = page.node;
  const shown = detail?.node || { node_id: selected };
  const file = config.source ? sourceOf(detail?.error ? null : detail, selected === node.node_id ? node : null) : "";
  return <div className="cm-node-page">
    <section className="cm-stage">
      <div className="cm-stage__bar">
        <Kind>{typeLabel(node.node_type)}</Kind>
        <strong className="cm-node-title" title={node.node_id}>{node.name}</strong>
        <span className="md-muted cm-small">Tick 1 / W / R / E hai bên node để mở rộng</span>
      </div>
      <FlowGraph key={node.node_id} nodes={rootNodes} edges={NO_EDGES} entry={node.node_id} initialExpand={START}
        selected={selected} onNodeClick={select} notify={notify} />
    </section>
    <aside className="cm-node-side">
      {page.flows.length ? <div className="cm-node-side__flows"><span className="cm-label">Thuộc luồng</span>
        {page.flows.map((flow) => <button key={flow.id} type="button" className="cm-node-flow" onClick={() => onOpenItem({ kind: "flow", id: flow.id })}>
          <md-icon>description</md-icon><span><b>{flow.name}</b><small>{flow.path}</small></span></button>)}
      </div> : <p className="md-muted cm-small cm-node-side__none">Node này chưa thuộc luồng nào đã tách.</p>}
      <div className="cm-node-side__notes"><NodeNotes nodeId={selected} notify={notify} /></div>
      <div className="cm-node-side__actions md-row">
        {history.length ? <Button icon="arrow_back" onClick={() => { setSelected(history.at(-1)); setHistory((current) => current.slice(0, -1)); }}>Quay lại</Button> : null}
        {selected !== node.node_id ? <Button variant="tonal" icon="hub" onClick={() => onOpenNode(selected)}>Mở graph từ node này</Button> : null}
        {file ? <Button icon="code" onClick={() => onSnippet(file, selected)}>Xem file nguồn</Button> : null}
      </div>
      <div className="cm-node-side__detail">
        <DetailPanel selected={{ ...shown, targetType: "NODE" }} detail={detail?.error ? null : detail}
          onSelectNode={select} localized={{}} loading={loading} error={detail?.error || ""} />
      </div>
    </aside>
  </div>;
}
