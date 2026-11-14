import React, { useEffect, useRef, useState } from "react";
import { swimlanes, typeLabel } from "../lib/text.js";

// Lanes are systems; each step is a card in the lane of the system it runs in, and arrows follow the
// step order, so the picture shows the flow moving from system to system.
export default function Swimlane({ steps, stepNodes, nodesById, activeStep, selected, onStep, onNode }) {
  const placed = steps.map((step, index) => ({ ...step, nodes: stepNodes[index] }));
  const { lanes, placement } = swimlanes(placed, nodesById);
  const board = useRef(null);
  const [arrows, setArrows] = useState([]);

  useEffect(() => {
    const draw = () => {
      const root = board.current;
      if (!root) return;
      const base = root.getBoundingClientRect();
      const boxes = steps.map((step) => root.querySelector(`[data-step="${CSS.escape(step.id)}"]`)?.getBoundingClientRect());
      const next = [];
      for (let index = 0; index + 1 < boxes.length; index += 1) {
        const from = boxes[index], to = boxes[index + 1];
        if (!from || !to) continue;
        const x1 = from.right - base.left, y1 = from.top + from.height / 2 - base.top;
        const x2 = to.left - base.left, y2 = to.top + to.height / 2 - base.top;
        const dx = Math.max(24, (x2 - x1) / 2);
        next.push({ id: `${steps[index].id}-${steps[index + 1].id}`, d: `M${x1},${y1} C${x1 + dx},${y1} ${x2 - dx},${y2} ${x2},${y2}`,
          cross: placement[index] !== placement[index + 1] });
      }
      setArrows(next);
    };
    draw();
    const observer = new ResizeObserver(draw);
    if (board.current) observer.observe(board.current);
    return () => observer.disconnect();
  }, [steps, stepNodes, placement.join("|")]); // eslint-disable-line react-hooks/exhaustive-deps

  if (!steps.length) return <div className="cm-canvas cm-canvas--empty"><p className="md-muted">Luồng này chưa có bước nào.</p></div>;
  return <div className="cm-lanes">
    <div className="cm-swim" ref={board} style={{ gridTemplateColumns: `160px repeat(${steps.length}, 260px)`, gridTemplateRows: `auto repeat(${lanes.length}, minmax(120px, auto))` }}>
      <div className="cm-swim__corner" />
      {steps.map((step, index) => <div key={step.id} className="cm-swim__col" style={{ gridColumn: index + 2, gridRow: 1 }}>Bước {index + 1}</div>)}
      {lanes.map((lane, row) => <React.Fragment key={lane.key}>
        <div className="cm-swim__lane" style={{ gridColumn: 1, gridRow: row + 2 }}><b>{lane.label}</b><small>{lane.types.map(typeLabel).join(", ").toLowerCase()}</small></div>
        <div className="cm-swim__track" style={{ gridColumn: `2 / span ${steps.length}`, gridRow: row + 2 }} />
      </React.Fragment>)}
      {placed.map((step, index) => {
        const row = lanes.findIndex((lane) => lane.key === placement[index]) + 2;
        const nodes = (step.nodes || []).map((id) => nodesById.get(id)).filter(Boolean);
        return <div key={step.id} data-step={step.id} role="button" tabIndex={0}
          className={`cm-swim__step${activeStep === step.id ? " is-active" : ""}`} style={{ gridColumn: index + 2, gridRow: row }}
          onClick={() => onStep(step.id)} onKeyDown={(event) => { if (event.key === "Enter") onStep(step.id); }}>
          <span className="cm-swim__no">B{index + 1}</span>
          <b>{step.name || "Chưa đặt tên"}</b>
          {step.actor ? <span className="cm-swim__actor">{step.actor}</span> : null}
          {(step.rules || []).map((rule, position) => <span key={position} className={`cm-swim__rule cm-swim__rule--${rule.status || "warn"}`}><md-icon>rule</md-icon>{rule.title}</span>)}
          <span className="cm-swim__nodes">{nodes.map((node) => <button key={node.node_id} type="button"
            className={`cm-ref${selected === node.node_id ? " cm-ref--sel" : ""}${node.system !== placement[index] ? " cm-ref--other" : ""}`}
            title={`${typeLabel(node.node_type)} · ${node.system || ""}`} onClick={(event) => { event.stopPropagation(); onNode(node.node_id); }}>{node.name}</button>)}</span>
        </div>;
      })}
      <svg className="cm-swim__arrows" aria-hidden="true">
        <defs><marker id="cm-swim-head" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto"><path d="M0,0 L10,5 L0,10 z" /></marker></defs>
        {arrows.map((arrow) => <path key={arrow.id} d={arrow.d} className={arrow.cross ? "is-cross" : ""} markerEnd="url(#cm-swim-head)" />)}
      </svg>
    </div>
  </div>;
}

