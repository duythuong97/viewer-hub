// Node detail beside the graph: names, description, properties, links.
import React from "react";
import { bilingualNames, formatLabel, friendlyDisplayText, identityText, localizedDescription, props } from "./lib/format.js";
import { erdHash } from "./lib/erd-layout.js";

// Nodes the ERD page can centre on (a column opens its table).
const ERD_TYPES = new Set(["TABLE", "COLUMN"]);

function Badge({ children, tone = "neutral" }) {
  return <span className={`cm-dbadge cm-dbadge--${tone}`}>{children}</span>;
}

function EntityIdentity({ node, localized, compact = false }) {
  return <span className={`cm-entity${compact ? " cm-entity--compact" : ""}`}>{identityText(node, localized)}</span>;
}

function EmptyState({ children }) {
  return <p className="cm-detail__empty">{children}</p>;
}

function DetailHeader({ selected, detail, localized }) {
  const isEdge = selected?.targetType === "EDGE" || selected?.edge_id;
  const node = detail?.node || (!isEdge ? selected : null);
  const edge = detail?.edge || (isEdge ? selected : null);
  const sourceNode = detail?.source || { node_id: edge?.source_node_id };
  const targetNode = detail?.target || { node_id: edge?.target_node_id };
  return <header className="cm-detail__header">
    <Badge tone={isEdge ? "edge" : "node"}>{isEdge ? "EDGE" : node?.node_type}</Badge>
    <h3>{isEdge ? edge?.edge_type || "Edge" : <EntityIdentity node={node} localized={localized} />}</h3>
    {isEdge ? <div className="cm-detail__endpoints"><EntityIdentity node={sourceNode} localized={localized} compact /><md-icon>arrow_forward</md-icon><EntityIdentity node={targetNode} localized={localized} compact /></div> : null}
    {isEdge && edge?.graph_layer ? <div><Badge>{edge.graph_layer}</Badge></div> : null}
  </header>;
}

function SemanticInfo({ semantic }) {
  if (!semantic) return null;
  return <details className="cm-sem-info">
    <summary aria-label={`Xem semantic: ${semantic.label}`}><md-icon>info</md-icon></summary>
    <span className="cm-sem-info__pop" role="tooltip">
      <strong>{semantic.label}</strong>
      <span>{semantic.definition}</span>
      <small>Xác nhận bởi {semantic.author_name}</small>
    </span>
  </details>;
}

function SemanticBranch({ item, nodes, businessSemantics, localized, onSelectNode }) {
  const semantic = businessSemantics[item.ref_node_id];
  const referencedNode = nodes[item.ref_node_id];
  return <li>
    <div className="cm-sem-row">
      <Badge>{formatLabel(item.type)}</Badge>
      {item.ref_node_id
        ? <button type="button" className="cm-link" onClick={() => onSelectNode?.(item.ref_node_id)} title={`Mở ${item.label}`}>
          <EntityIdentity node={referencedNode || { node_id: item.ref_node_id }} localized={localized} compact /></button>
        : <span>{item.label}</span>}
      <SemanticInfo semantic={semantic} />
      {item.action ? <code>{item.action}</code> : null}
    </div>
    {item.children?.length ? <ul>{item.children.map((child, index) => <SemanticBranch key={`${child.type}:${child.ref_node_id || child.label}:${index}`}
      item={child} nodes={nodes} businessSemantics={businessSemantics} localized={localized} onSelectNode={onSelectNode} />)}</ul> : null}
  </li>;
}

function SemanticSection({ title, items, ...rest }) {
  if (!items?.length) return null;
  return <section>
    <h5>{title}</h5>
    <ul>{items.map((item, index) => <SemanticBranch key={`${title}:${item.name || item.label}:${index}`}
      item={{ type: item.type || title, label: item.label || [item.name, item.type].filter(Boolean).join(": "), ...item }} {...rest} />)}</ul>
  </section>;
}

function NodeOverview({ node, nodes = {}, businessSemantics = {}, localized = {}, onSelectNode }) {
  if (!node) return <EmptyState>Không có chi tiết node.</EmptyState>;
  const semanticTree = props(node).semantic_tree;
  const hasV2Content = semanticTree?.version === 2 && ["parameters", "steps", "outputs", "exceptions", "analysis_notes"].some((key) => semanticTree[key]?.length);
  if (!hasV2Content && !semanticTree?.children?.length) return <EmptyState>Node này không có semantic tree.</EmptyState>;
  const shared = { nodes, businessSemantics, localized, onSelectNode };
  return <section className="cm-sem">
    <h4>Semantic tree</h4>
    {semanticTree.version === 2 ? <>
      <div className="cm-sem-row"><Badge>operation</Badge><EntityIdentity node={node} localized={localized} compact /><SemanticInfo semantic={businessSemantics[node.node_id]} /></div>
      {semanticTree.summary ? <p>{semanticTree.summary}</p> : null}
      <SemanticSection title="Parameters" items={semanticTree.parameters} {...shared} />
      <SemanticSection title="Steps" items={semanticTree.steps} {...shared} />
      <SemanticSection title="Outputs" items={semanticTree.outputs} {...shared} />
      <SemanticSection title="Exceptions" items={semanticTree.exceptions} {...shared} />
      <SemanticSection title="Analysis notes" items={semanticTree.analysis_notes} {...shared} />
    </> : <ul><SemanticBranch item={semanticTree} {...shared} /></ul>}
  </section>;
}

function ColumnsTable({ columns, localized }) {
  if (!columns?.length) return <EmptyState>Bảng này không có cột nào.</EmptyState>;
  return <div className="md-table-wrap cm-columns">
    <table className="md-table">
      <thead><tr><th>#</th><th>Column code</th><th>日本語名</th><th>English name</th><th>Data type</th><th>Nullable</th><th>Related table</th><th>Note</th></tr></thead>
      <tbody>{columns.map((column, index) => {
        const p = props(column);
        const names = bilingualNames(column, localized);
        const code = friendlyDisplayText(p.column_code || column.technical_name, column.node_id);
        const descriptionJa = localizedDescription(column, localized, "ja");
        const descriptionEn = localizedDescription(column, localized, "en");
        const nullable = p.nullable == null ? null : ![false, "false", "N", "NO", 0].includes(p.nullable);
        return <tr key={column.node_id}>
          <td className="md-table__num">{p.ordinal_position || index + 1}</td>
          <td><strong>{code || "—"}</strong></td>
          <td lang="ja">{names.ja || "—"}{descriptionJa ? <small className="cm-columns__desc">{descriptionJa}</small> : null}</td>
          <td lang="en">{names.en || "—"}{descriptionEn ? <small className="cm-columns__desc">{descriptionEn}</small> : null}</td>
          <td><span className="md-badge">{p.data_type || "—"}</span></td>
          <td><span className={`cm-nullable${nullable === false ? " cm-nullable--required" : ""}`}>{nullable == null ? "—" : nullable ? "Yes" : "No"}</span></td>
          <td>{p.relation_table || "—"}</td>
          <td>{p.note || "—"}</td>
        </tr>;
      })}</tbody>
    </table>
  </div>;
}

export default function DetailPanel({ selected, detail, onSelectNode, localized = {}, loading, error, actions }) {
  if (!selected) return <section className="cm-detail"><EmptyState>Chọn một node.</EmptyState></section>;
  if (loading && !detail) return <section className="cm-detail"><md-linear-progress indeterminate /></section>;
  if (error && !detail) return <section className="cm-detail"><EmptyState>{error}</EmptyState></section>;
  const node = detail?.node || selected;
  return <section className="cm-detail">
    <DetailHeader selected={selected} detail={detail} localized={localized} />
    {actions}
    {ERD_TYPES.has(node.node_type) && node.node_id ? <a className="cm-erd-link" href={erdHash({ table: node.node_id })}>
      <md-icon aria-hidden="true">schema</md-icon>Xem ERD{node.node_type === "COLUMN" ? " của bảng" : ""}</a> : null}
    <div className="cm-detail__body">
      {node.node_type === "TABLE"
        ? <ColumnsTable columns={detail?.columns || []} localized={localized} />
        : <NodeOverview node={node} nodes={detail?.semantic_tree_nodes || {}} businessSemantics={detail?.semantic_tree_business_semantics || {}}
          localized={localized} onSelectNode={onSelectNode} />}
    </div>
  </section>;
}
