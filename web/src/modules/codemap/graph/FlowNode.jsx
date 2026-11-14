import React from "react";
import { Handle, Position } from "@xyflow/react";
import { expansionIntentKey, groupLoadState, isExternalNode } from "../lib/flow-state.js";
import { directionLabels, flowKey, modeLabels, modes, nodeTypeKinds } from "../lib/constants.js";
import { formatLabel, identityParts } from "../lib/format.js";

// Material Symbols per node kind (was lucide-react).
const NODE_ICONS = {
  table: "table",
  code: "code",
  trigger: "bolt",
  file: "description",
  sequence: "linear_scale",
  "source-file": "draft",
  repository: "inventory_2",
  application: "web_asset",
  unknown: "help_center",
  detail: "deployed_code",
};

function flowNodeKind(nodeType = "") {
  return nodeTypeKinds[nodeType] || "detail";
}

// The 1 / W / R / E expansion toggles on both sides of a node.
export function NodeFlowControls({ node, direction, data }) {
  if (!node?.node_id || !data?.onToggleFlow) return null;
  return <div className={`cm-node-ctl nodrag cm-node-ctl--${direction}`} aria-label={`${directionLabels[direction]} node flow controls`}
    onClick={(event) => event.stopPropagation()} onMouseDown={(event) => event.stopPropagation()}>
    {modes.map((mode) => {
      const key = flowKey(node.node_id, mode, direction, data.semantic, data.filters);
      const state = groupLoadState(data.loadStates, key);
      const active = Boolean(data.intents?.[expansionIntentKey(node.node_id, mode, direction)] || data.groups?.[key]);
      const title = [directionLabels[direction], modeLabels[mode], state.loading ? "loading" : "", state.error || "", state.truncated ? "truncated" : ""].filter(Boolean).join(" · ");
      const classes = ["cm-node-ctl__chip", active ? "is-active" : "", state.loading ? "is-loading" : "", state.error ? "is-error" : "", state.truncated ? "is-truncated" : ""].filter(Boolean).join(" ");
      return <label key={key} className={classes} title={title}>
        <input aria-label={`${directionLabels[direction]} ${modeLabels[mode]}`} type="checkbox" checked={active}
          onChange={(event) => data.onToggleFlow(node, mode, direction, event.target.checked)} />
        {mode}
      </label>;
    })}
  </div>;
}

// A system at the System level: the systems the flow crosses, what each holds.
function SystemNode({ node, data }) {
  const kinds = Object.entries(node.kinds || {});
  return <div className="cm-node cm-node--system">
    <Handle type="target" position={Position.Left} className="cm-handle" />
    <Handle type="source" position={Position.Right} className="cm-handle" />
    <div className="cm-node__head"><md-icon aria-hidden="true">dns</md-icon><strong>Hệ thống</strong></div>
    <div className="cm-node__system-name" title={node.name}>{node.name}</div>
    <div className="cm-node__kinds">{kinds.slice(0, 4).map(([type, count]) => <span key={type}>{count} {formatLabel(type).toLowerCase()}</span>)}
      {kinds.length > 4 ? <span>+{kinds.length - 4} loại</span> : null}</div>
  </div>;
}

export function FlowNode({ data }) {
  const node = data.node;
  if (node.synthetic) return <SystemNode node={node} data={data} />;
  const kind = flowNodeKind(node.node_type);
  const identity = identityParts(node, data.localized);
  return <div className={`cm-node cm-node--${kind}${isExternalNode(node) ? " cm-node--external" : ""}`}>
    <Handle type="target" position={Position.Left} className="cm-handle" />
    <Handle type="source" position={Position.Right} className="cm-handle" />
    <NodeFlowControls node={node} direction="in" data={data} />
    <NodeFlowControls node={node} direction="out" data={data} />
    <div className="cm-node__head">
      <md-icon aria-hidden="true">{NODE_ICONS[kind] || "deployed_code"}</md-icon>
      <strong>{formatLabel(node.node_type)}</strong>
    </div>
    <div className="cm-node__identity">
      <span className="cm-node__code" title={identity.code}><small>Mã</small><strong>{identity.code}</strong></span>
      <span lang="ja" title={identity.ja}><small>JA</small>{identity.ja || "—"}</span>
      <span lang="en" title={identity.en}><small>EN</small>{identity.en || "—"}</span>
    </div>
    {data.folded?.count && data.onUnfold ? <button type="button" className={`cm-node-fold nodrag${data.foldedOpen ? " is-open" : ""}`}
      title={Object.entries(data.folded.kinds || {}).map(([type, count]) => `${count} ${formatLabel(type)}`).join(" · ")}
      onClick={(event) => { event.stopPropagation(); data.onUnfold(node, !data.foldedOpen); }} onMouseDown={(event) => event.stopPropagation()}>
      <md-icon>{data.foldedOpen ? "unfold_less" : "data_object"}</md-icon>
      {data.foldedOpen ? `Gấp ${data.folded.count} kiểu dữ liệu` : `Dùng ${data.folded.count} kiểu dữ liệu`}
    </button> : null}
  </div>;
}
