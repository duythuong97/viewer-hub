import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Background, Controls, MarkerType, ReactFlow } from "@xyflow/react";
import { api } from "../api.js";
import { buildAutoLayout } from "../lib/layout.js";
import { edgeColor, flowFiltersKey, flowKey } from "../lib/constants.js";
import { FlowNode } from "./FlowNode.jsx";
import { baseIntentChecked, componentSeeds, connectedNodes, entryIntentEdges, placeNodes, toggleBaseIntent } from "../lib/graph-place.js";
import {
  expansionIntentKey,
  materializeGroups,
  mergeExpansionIntent,
  mergeGroup,
  removeExpansionIntent,
  removeGroup,
  removeGroupLoadState,
  setGroupLoadState,
} from "../lib/flow-state.js";
import { Button } from "../../../md/react.jsx";

// Graph nodes are the explorer's FlowNode, so the 1/W/R/E checkboxes on both sides keep working:
// ticking one loads that expansion from /flow and adds its nodes around the flow.
const StepFlowNode = React.memo(function StepFlowNode(props) {
  const tags = props.data.tags || [];
  return <>
    {tags.length ? <span className="cm-gtags">{tags.map((tag) => <b key={tag}>B{tag}</b>)}</span> : null}
    <FlowNode {...props} />
  </>;
});
const nodeTypes = { flowNode: StepFlowNode };
// The flow page (FlowView.jsx) picks the lens ("run" | "deps", codemap/levels.py LENSES: what a lens leaves out is
// folded into a count) and the level of detail; the graph follows them (`lens`, `semantic`).
const filtersFor = (lens) => `${flowFiltersKey(MAX_EXPANSION_NODES)}&lens=${lens}`;
const MAX_EXPANSION_NODES = 200;

// Expansions skip structural containment (table → columns, file → methods): one hop would otherwise pull in
// everything. Containment of the parts that run stays: a screen's actions, a jobnet's jobs, a method's SQL.
const FLOW_PART_TYPES = new Set(["UI_ACTION", "JOB", "INLINE_SQL", "SQL_STATEMENT", "PROCEDURE", "FUNCTION", "LOCAL_ROUTINE"]);

function withoutStructure(rootId, data) {
  const types = new Map((data.nodes || []).map((node) => [node.node_id, node.node_type]));
  const edges = (data.edges || []).filter((edge) => edge.edge_type !== "HAS_COLUMN" && (edge.graph_layer !== "STRUCTURAL"
    || (edge.edge_type === "CONTAINS" && FLOW_PART_TYPES.has(types.get(edge.target_node_id)))));
  const linked = new Set([rootId]);
  edges.forEach((edge) => { linked.add(edge.source_node_id); linked.add(edge.target_node_id); });
  return { nodes: (data.nodes || []).filter((node) => linked.has(node.node_id) && node.node_type !== "COLUMN"), edges, folded: data.folded || {} };
}

// Between two systems: what happens, short enough to fit between the boxes ("ghi ×2 · đọc").
const WRITE_KINDS = new Set(["INSERTS", "UPDATES", "DELETES", "MERGES", "WRITES", "LOADS_INTO"]);
const READ_KINDS = new Set(["READS", "REMOTE_READS"]);
function systemEdgeLabel(kinds) {
  const totals = { ghi: 0, "đọc": 0, "gọi": 0 };
  Object.entries(kinds).forEach(([kind, count]) => {
    totals[WRITE_KINDS.has(kind) ? "ghi" : READ_KINDS.has(kind) ? "đọc" : "gọi"] += count;
  });
  return Object.entries(totals).filter(([, count]) => count).map(([verb, count]) => (count > 1 ? `${verb} ×${count}` : verb)).join(" · ");
}

function toGraphNode(node) {
  return { ...node, technical_name: node.name || node.technical_name, default_display_name: node.display_name || node.name };
}

export default function FlowGraph({ nodes: flowNodesAll, edges: flowEdgesAll, levels, folded: baseFolded, steps = [], stepNodes = [], activeStep, selected, picking, entry, initialExpand, onNodeClick, onShown, notify,
  lens: wantedLens = "run", semantic: wantedSemantic = "TECHNICAL", onLens }) {
  const instance = useRef(null);
  const canvasRef = useRef(null);
  const requests = useRef(new Map());
  const [semantic, setSemantic] = useState(wantedSemantic);
  const [lens, setLens] = useState(wantedLens);
  // System/Application project the flow itself too, not only the expansions.
  const level = semantic !== "TECHNICAL" ? levels?.[semantic] : null;
  const nodes = useMemo(() => {
    if (!level) return flowNodesAll;
    if (level.system_nodes) return level.system_nodes; // System: one box per system, members inside
    const keep = new Set(level.nodes);
    return flowNodesAll.filter((node) => keep.has(node.node_id));
  }, [flowNodesAll, level]);
  const edges = level ? level.edges : flowEdgesAll;
  const [groups, setGroups] = useState({});
  const [groupStates, setGroupStates] = useState({});
  const [intents, setIntents] = useState({});
  const [localized, setLocalized] = useState({});
  // Base (flow) edges the user hid by unticking an E/W/R box; see graph-place.js for the rules.
  const [hidden, setHidden] = useState(() => new Set());
  // Nodes the user dragged keep their spot; `moving` holds the position while a drag is in progress.
  const [dragged, setDragged] = useState({});
  const [moving, setMoving] = useState(null);
  // Sizes React Flow measured; handed back on every render so nodes are not re-measured (and hidden) each time.
  const [measured, setMeasured] = useState(() => new Map());
  const lastPlaced = useRef(new Map());
  const autoFitted = useRef(false);
  const filters = filtersFor(lens);
  const baseEdges = useMemo(() => edges.map((edge) => ({ ...edge, source_node_id: edge.source, target_node_id: edge.target })), [edges]);
  // The flow belongs to its entry's E box only: other nodes' boxes stay unticked until someone expands them.
  // At System level the entry is the entry's system box.
  const graphEntry = level?.entry || entry;
  const owned = useMemo(() => entryIntentEdges(baseEdges, graphEntry), [baseEdges, graphEntry]);

  useEffect(() => {
    const names = {};
    nodes.forEach((node) => {
      if (node.names?.ja || node.names?.en) names[node.node_id] = { ja: { name: node.names.ja }, en: { name: node.names.en } };
    });
    setLocalized((current) => ({ ...current, ...names }));
  }, [nodes]);

  useEffect(() => () => requests.current.forEach((controller) => controller.abort()), []);

  const loadGroup = useCallback(async (node, mode, direction, level, lensValue = lens) => {
    const key = flowKey(node.node_id, mode, direction, level, filtersFor(lensValue));
    requests.current.get(key)?.abort();
    const controller = new AbortController();
    requests.current.set(key, controller);
    setGroupStates((current) => setGroupLoadState(current, key, { loading: true, error: "", truncated: false }));
    try {
      const data = await api(`/flow?node_id=${encodeURIComponent(node.node_id)}&mode=${mode}&direction=${direction}&max_nodes=${MAX_EXPANSION_NODES}&semantic_level=${level}&lens=${lensValue}`, { signal: controller.signal });
      if (requests.current.get(key) !== controller) return;
      const group = withoutStructure(node.node_id, data);
      setGroups((current) => mergeGroup(current, key, group));
      // Ticking an expansion means the user wants its edges, including flow edges they hid earlier.
      const ids = new Set(group.edges.map((edge) => edge.edge_id));
      setHidden((current) => ([...current].some((id) => ids.has(id)) ? new Set([...current].filter((id) => !ids.has(id))) : current));
      setGroupStates((current) => setGroupLoadState(current, key, { loading: false, error: "", truncated: Boolean(data.truncated) }));
      const named = (data.nodes || []).map((item) => item.node_id).slice(0, 300);
      if (named.length) {
        const body = await api(`/localization?${named.map((id) => `target_id=${encodeURIComponent(id)}`).join("&")}`).catch(() => null);
        if (body?.items) setLocalized((current) => ({ ...current, ...body.items }));
      }
      if (data.truncated) notify?.(`Đã cắt ở ${MAX_EXPANSION_NODES} node`);
    } catch (error) {
      if (error.name === "AbortError") return;
      setIntents((current) => removeExpansionIntent(current, node.node_id, mode, direction));
      setGroupStates((current) => setGroupLoadState(current, key, { loading: false, error: error.message, truncated: false }));
      notify?.(error.message);
    } finally {
      if (requests.current.get(key) === controller) requests.current.delete(key);
    }
  }, [lens, notify]);

  const toggleFlow = useCallback((node, mode, direction, checked) => {
    const intent = expansionIntentKey(node.node_id, mode, direction);
    const key = flowKey(node.node_id, mode, direction, semantic, filters);
    if (owned.has(intent)) {
      // A walk the flow already shows (E/W/R): unticking hides its edges, ticking shows them again.
      setHidden((current) => toggleBaseIntent(current, owned, intent, checked));
      if (checked) return;
    }
    if (!checked) {
      requests.current.get(key)?.abort();
      setIntents((current) => removeExpansionIntent(current, node.node_id, mode, direction));
      setGroupStates((current) => removeGroupLoadState(current, key));
      setGroups((current) => removeGroup(current, key));
      return;
    }
    setIntents((current) => mergeExpansionIntent(current, node, mode, direction));
    void loadGroup(node, mode, direction, semantic);
  }, [semantic, filters, loadGroup, owned]);

  // A graph opened from a single node starts with its own 1-hop neighbours, like ticking "1" on both sides.
  useEffect(() => {
    const root = flowNodesAll.find((node) => node.node_id === entry);
    if (!root || !initialExpand?.length) return;
    initialExpand.forEach(([mode, direction]) => toggleFlow(toGraphNode(root), mode, direction, true));
  }, [entry]); // eslint-disable-line react-hooks/exhaustive-deps

  function changeSemantic(level) {
    if (level === semantic) return;
    requests.current.forEach((controller) => controller.abort());
    setSemantic(level);
    setGroups({});
    setGroupStates({});
    setHidden(new Set());
    setDragged({});
    Object.values(intents).forEach((intent) => void loadGroup(intent.node, intent.mode, intent.direction, level));
  }

  function changeLens(next) {
    if (next === lens) return;
    requests.current.forEach((controller) => controller.abort());
    setLens(next);
    setGroups({});
    setGroupStates({});
    setHidden(new Set());
    // A folded group means nothing in the Dependencies lens, where those edges are drawn anyway.
    const kept = Object.values(intents).filter((intent) => next !== "deps" || intent.mode !== "U");
    if (kept.length !== Object.keys(intents).length) {
      setIntents(Object.fromEntries(Object.entries(intents).filter(([, intent]) => next !== "deps" || intent.mode !== "U")));
    }
    kept.forEach((intent) => void loadGroup(intent.node, intent.mode, intent.direction, semantic, next));
  }

  // The page changed the lens or the level: reload the expansions for it.
  useEffect(() => { changeLens(wantedLens); }, [wantedLens]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { changeSemantic(wantedSemantic); }, [wantedSemantic]); // eslint-disable-line react-hooks/exhaustive-deps

  function clearExpansions() {
    requests.current.forEach((controller) => controller.abort());
    setGroups({}); setGroupStates({}); setIntents({}); setHidden(new Set()); setDragged({});
    lastPlaced.current = new Map();
    autoFitted.current = false;
    // A node page's starting point is its 1-hop neighbourhood, so "back to the start" means that again.
    const root = flowNodesAll.find((node) => node.node_id === entry);
    if (root && initialExpand?.length) {
      initialExpand.forEach(([mode, direction]) => {
        setIntents((current) => mergeExpansionIntent(current, toGraphNode(root), mode, direction));
        void loadGroup(toGraphNode(root), mode, direction, semantic);
      });
    }
  }

  const activeIndex = steps.findIndex((step) => step.id === activeStep);
  const memberIds = (node) => node.members || [node.node_id];
  const focus = activeIndex >= 0 ? new Set(level?.system_nodes
    ? level.system_nodes.filter((box) => box.members.some((id) => stepNodes[activeIndex].includes(id))).map((box) => box.node_id)
    : stepNodes[activeIndex]) : null;
  const graph = useMemo(() => {
    const expanded = materializeGroups(null, groups);
    const byId = new Map(nodes.map((node) => [node.node_id, toGraphNode(node)]));
    expanded.nodes.forEach((node) => { if (!byId.has(node.node_id)) byId.set(node.node_id, { ...node, expanded: true }); });
    const shown = new Map(baseEdges.filter((edge) => !hidden.has(edge.edge_id)).map((edge) => [edge.edge_id, edge]));
    expanded.edges.forEach((edge) => {
      if (!shown.has(edge.edge_id) && !hidden.has(edge.edge_id) && byId.has(edge.source_node_id) && byId.has(edge.target_node_id)) shown.set(edge.edge_id, edge);
    });
    // Nodes stay while a shown edge still connects them to a seed: the entry, or one node of every part of the
    // flow graph that is not joined to it (a level projection can split the flow; a hand-added node has no edges).
    const seeds = componentSeeds(nodes.map((node) => node.node_id), baseEdges, graphEntry);
    const linked = connectedNodes(seeds, [...shown.values()]);
    const keep = [...byId.values()].filter((node) => linked.has(node.node_id));
    return { nodes: keep, edges: [...shown.values()].filter((edge) => linked.has(edge.source_node_id) && linked.has(edge.target_node_id)) };
  }, [nodes, baseEdges, groups, hidden, graphEntry]);
  // The flow's own nodes are laid out once; expansions never move them.
  const basePositions = useMemo(() => new Map(buildAutoLayout(nodes.map(toGraphNode), baseEdges, graphEntry, {}).map((node) => [node.node_id, node.position])), [nodes, baseEdges, graphEntry]);
  const positions = useMemo(() => {
    const allEdges = [...baseEdges, ...Object.values(groups).flatMap((group) => group.edges || [])];
    const order = [...new Set(Object.values(groups).flatMap((group) => (group.nodes || []).map((node) => node.node_id)))];
    // Expansion nodes already on screen keep their place when other groups come and go.
    const kept = order.filter((id) => lastPlaced.current.has(id)).map((id) => [id, lastPlaced.current.get(id)]);
    const placed = placeNodes(new Map([...kept, ...basePositions, ...Object.entries(dragged)]), [...nodes.map((node) => node.node_id), ...order], allEdges);
    lastPlaced.current = placed;
    return placed;
  }, [basePositions, nodes, baseEdges, groups, dragged]);
  const layout = useMemo(() => graph.nodes.map((node) => ({ ...node, position: (moving?.id === node.node_id && moving.position) || positions.get(node.node_id) || { x: 0, y: 0 } })), [graph, positions, moving]);
  const onNodesChange = useCallback((changes) => {
    const sizes = changes.filter((change) => change.type === "dimensions" && change.dimensions);
    if (sizes.length) {
      setMeasured((current) => {
        const changed = sizes.filter((change) => {
          const old = current.get(change.id);
          return !old || old.width !== change.dimensions.width || old.height !== change.dimensions.height;
        });
        if (!changed.length) return current;
        const next = new Map(current);
        changed.forEach((change) => next.set(change.id, change.dimensions));
        return next;
      });
    }
    for (const change of changes) {
      if (change.type !== "position") continue;
      if (change.dragging && change.position) setMoving({ id: change.id, position: change.position });
      else if (change.dragging === false) {
        setMoving((current) => {
          if (current?.id === change.id) setDragged((saved) => ({ ...saved, [change.id]: change.position || current.position }));
          return null;
        });
      }
    }
  }, []);
  const intentsShown = useMemo(() => {
    const merged = { ...intents };
    const shown = new Set(graph.edges.map((edge) => edge.edge_id));
    owned.forEach((_, key) => { if (baseIntentChecked(shown, owned, key)) merged[key] = true; });
    return merged;
  }, [intents, owned, graph]);

  // Folded USES/MAPS_TO counts: the flow's own nodes (from the page) and each expansion's (from /flow).
  const foldedMap = useMemo(() => {
    if (lens === "deps" || level?.system_nodes) return {};
    const merged = { ...(semantic === "TECHNICAL" ? baseFolded || {} : {}) };
    Object.values(groups).forEach((group) => Object.assign(merged, group.folded || {}));
    return merged;
  }, [baseFolded, groups, lens, semantic, level]);
  const unfold = useCallback((node, open) => toggleFlow(node, "U", "out", open), [toggleFlow]);
  const foldedShown = layout.reduce((sum, node) => sum + (intents[expansionIntentKey(node.node_id, "U", "out")] ? 0 : foldedMap[node.node_id]?.count || 0), 0);
  const flowNodes = useMemo(() => layout.map((node) => {
    const tags = stepNodes.map((ids, index) => (memberIds(node).some((id) => ids.includes(id)) ? index + 1 : 0)).filter(Boolean);
    const inFocus = focus?.has(node.node_id);
    return {
      id: node.node_id, type: "flowNode", position: node.position, measured: measured.get(node.node_id),
      className: [selected === node.node_id ? "cm-sel" : "", focus && !inFocus ? "cm-dim" : "", inFocus ? "cm-focus" : "", picking ? "cm-pick" : "", node.expanded ? "cm-expanded" : ""].filter(Boolean).join(" "),
      data: { node, tags, localized, groups, loadStates: groupStates, intents: intentsShown, onToggleFlow: toggleFlow, semantic, filters,
        folded: foldedMap[node.node_id], foldedOpen: Boolean(intents[expansionIntentKey(node.node_id, "U", "out")]), onUnfold: unfold },
    };
  }), [layout, stepNodes, activeIndex, selected, picking, measured, localized, groups, groupStates, intentsShown, toggleFlow, semantic, filters, foldedMap, intents, unfold]); // eslint-disable-line react-hooks/exhaustive-deps
  const flowEdges = useMemo(() => graph.edges.map((edge) => {
    const dim = focus && !(focus.has(edge.source_node_id) && focus.has(edge.target_node_id));
    return {
      id: edge.edge_id, source: edge.source_node_id, target: edge.target_node_id, type: "default",
      label: edge.kinds ? systemEdgeLabel(edge.kinds)
        : edge.manual ? `${edge.edge_type} · tay` : edge.edge_type,
      className: [dim ? "cm-edge-dim" : "", edge.manual ? "cm-edge-manual" : ""].filter(Boolean).join(" "), animated: false,
      style: { stroke: edgeColor(edge.edge_type), strokeWidth: 1.6, ...(edge.manual ? { strokeDasharray: "6 4" } : {}) },
      markerEnd: { type: MarkerType.ArrowClosed, color: edgeColor(edge.edge_type), width: 14, height: 14 },
      labelBgPadding: [6, 3], labelBgBorderRadius: 8,
    };
  }), [graph, activeIndex]); // eslint-disable-line react-hooks/exhaustive-deps
  const fit = useCallback(() => {
    const ids = focus ? [...focus] : null;
    instance.current?.fitView({ padding: 0.15, duration: 300, minZoom: 0.65, maxZoom: 1, nodes: ids?.map((id) => ({ id })) });
  }, [activeIndex]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    const timer = setTimeout(fit, 60);
    return () => clearTimeout(timer);
  }, [semantic]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { const timer = setTimeout(fit, 30); return () => clearTimeout(timer); }, [fit]);
  // A node page starts from one node; fit once its first expansions have arrived.
  const loading = Object.values(groupStates).some((state) => state?.loading);
  useEffect(() => {
    if (!initialExpand?.length || autoFitted.current || loading || !Object.keys(groups).length) return undefined;
    autoFitted.current = true;
    const timer = setTimeout(fit, 60);
    return () => clearTimeout(timer);
  }, [loading, groups]); // eslint-disable-line react-hooks/exhaustive-deps
  // Selecting a node never zooms; the view only pans when the node is off screen (e.g. picked from the doc).
  useEffect(() => {
    const flow = instance.current;
    const node = selected && flow?.getNode(selected);
    const box = canvasRef.current?.getBoundingClientRect();
    if (!node || !box) return;
    const point = flow.flowToScreenPosition(node.position);
    if (point.x > box.left && point.x < box.right - 120 && point.y > box.top && point.y < box.bottom - 60) return;
    flow.setCenter(node.position.x + 130, node.position.y + 50, { zoom: flow.getZoom(), duration: 300 });
  }, [selected]);
  useEffect(() => { onShown?.({ nodes: graph.nodes.length, edges: graph.edges.length, level: semantic }); }, [graph, semantic]); // eslint-disable-line react-hooks/exhaustive-deps
  const expansions = Object.keys(intents).length + hidden.size;
  if (!flowNodesAll.length) return <div className="cm-canvas cm-canvas--empty"><p className="md-muted">Luồng này chưa có node nào trong graph.</p></div>;
  return <div className="cm-canvas" ref={canvasRef}>
    <div className="cm-canvas__tools">
      {foldedShown ? <span className="cm-folded-note"><md-icon>unfold_less</md-icon>Đang gấp {foldedShown} kiểu dữ liệu / service
        <button type="button" className="cm-link" onClick={() => onLens?.("deps")}>Hiện hết</button></span> : null}
      {expansions ? <Button variant="tonal" icon="undo" onClick={clearExpansions}>Về graph ban đầu</Button> : null}
    </div>
    {loading && (
      <div className="vh-canvas-overlay">
        <md-circular-progress indeterminate style={{ width: 36, height: 36 }}></md-circular-progress>
        <p>Đang tối ưu vị trí hiển thị cho {flowNodes.length} thành phần…</p>
      </div>
    )}
    <ReactFlow nodes={flowNodes} edges={flowEdges} nodeTypes={nodeTypes} onInit={(value) => { instance.current = value; fit(); }}
      onNodeClick={(_, node) => {
        const box = node.data?.node;
        if (box?.synthetic) { notify?.(`${box.name}: ${box.members.length} node. Chọn Application hoặc Technical để xem từng node.`); return; }
        onNodeClick(node.id);
      }} onNodesChange={onNodesChange} nodesDraggable nodesConnectable={false} minZoom={0.15} maxZoom={1.6} proOptions={{ hideAttribution: true }}>
      <Background gap={20} size={1.2} />
      <Controls showInteractive={false} />
    </ReactFlow>
  </div>;
}

