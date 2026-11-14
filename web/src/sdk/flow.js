// Addon SDK v1: React Flow of the Hub ("@vh/flow"), for pages that draw editable node / edge canvases (drag, connect,
// zoom, groups) without bundling React Flow. Same version and the same React as the Hub's Code map. Its stylesheet is
// added to the page on first import. layoutGraph() lays out big nested graphs in a Web Worker.
import flowCss from "@xyflow/react/dist/style.css?url";
import { layoutGraph as layoutNow } from "./graph-layout.js";

export {
  ReactFlow, ReactFlowProvider, Background, BackgroundVariant, Controls, ControlButton, MiniMap, Panel, Handle, Position,
  MarkerType, ConnectionMode, ConnectionLineType, SelectionMode, NodeResizer, NodeToolbar, BaseEdge, EdgeLabelRenderer,
  ViewportPortal, getBezierPath, getSmoothStepPath, getStraightPath, applyNodeChanges, applyEdgeChanges, addEdge,
  useReactFlow, useNodesState, useEdgesState, useStore, useStoreApi, useViewport, useOnViewportChange,
  useOnSelectionChange, useNodesInitialized, useInternalNode, useUpdateNodeInternals, useKeyPress,
} from "@xyflow/react";

if (typeof document !== "undefined" && !document.querySelector("link[data-vh-flow]")) {
  const link = document.createElement("link");
  link.rel = "stylesheet";
  link.href = flowCss;
  link.dataset.vhFlow = "1";
  document.head.appendChild(link);
}

let worker = null;
let seq = 0;
const waiting = new Map();

function layoutWorker() {
  if (worker === null) {
    try {
      worker = new Worker(new URL("./graph-layout.worker.js", import.meta.url), { type: "module" });
      worker.onmessage = (event) => {
        const { id, result, error } = event.data || {};
        const job = waiting.get(id);
        if (!job) return;
        waiting.delete(id);
        if (error) job.reject(new Error(error));
        else job.resolve(result);
      };
      worker.onerror = () => {
        for (const job of waiting.values()) job.fallback();
        waiting.clear();
        worker = false;
      };
    } catch {
      worker = false;
    }
  }
  return worker;
}

/**
 * Lays out a nested graph (layered, left → right or top → bottom); resolves to {id: {x, y, width, height}} with x / y
 * relative to the parent node, as React Flow sub-flows use. nodes: [{id, parent?, width, height, folded?}] (a node with
 * children gets the size that fits them; a folded one keeps its size and gets inner: {width, height} for when it is
 * opened); edges: [{source, target}]. options: {direction: "LR" | "TB", nodeGap,
 * rankGap, padding, header}. Runs in a Web Worker (the page stays responsive), on the page if workers are unavailable.
 */
export function layoutGraph({ nodes, edges }, options = {}) {
  const input = {
    nodes: (nodes || []).map((n) => ({ id: n.id, parent: n.parent ?? null, width: n.width, height: n.height, folded: !!n.folded })),
    edges: (edges || []).map((e) => ({ source: e.source, target: e.target })),
  };
  const local = () => layoutNow(input, options);
  const w = layoutWorker();
  if (!w) return Promise.resolve().then(local);
  return new Promise((resolve, reject) => {
    const id = ++seq;
    waiting.set(id, { resolve, reject, fallback: () => { try { resolve(local()); } catch (err) { reject(err); } } });
    w.postMessage({ id, input, options });
  });
}

export default { layoutGraph };
