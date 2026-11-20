import React from "react";
import { PART_LABELS, RULE_LABELS, inlineTokens, paragraphs, partCounts, resolveCitation } from "./lib/text.js";

// Who wrote a part (AI or a person), and a warning when its code changed since a person saved it.
export function Status({ status, by, changed }) {
  if (!status) return null;
  const person = status === "edited" || status === "approved";
  return <>
    <span className={`cm-status cm-status--${person ? "edited" : "ai"}`}>{PART_LABELS[status] || status}{person && by ? ` · ${by}` : ""}</span>
    {changed ? <span className="cm-status cm-status--kn-needs_review" title="Hành vi của các node phần này mô tả đã khác lúc lưu. Đọc lại code rồi sửa (hoặc lưu lại nếu vẫn đúng).">Code đã đổi</span> : null}
  </>;
}

export function RuleStatus({ status }) {
  return <span className={`cm-status cm-status--rule-${status || "warn"}`}>{RULE_LABELS[status] || RULE_LABELS.warn}</span>;
}

export function ProgressBar({ parts = [], max = 8 }) {
  const shown = parts.slice(0, max);
  const counts = partCounts(parts);
  const label = `${counts.person}/${counts.total} phần do người viết, ${counts.ai} phần AI viết`;
  return <span className="cm-mbar" title={label} aria-label={label}>
    {shown.map((part, index) => <i key={index} className={`cm-mbar--${part}`} />)}
  </span>;
}

// Renders document text: paragraphs, **bold**, `code` and [[node]] citations as links.
export function RichText({ text, lookup, selected, onCite }) {
  const blocks = paragraphs(text);
  if (!blocks.length) return null;
  return <div className="cm-prose">
    {blocks.map((block, index) => <p key={index}><Inline text={block} lookup={lookup} selected={selected} onCite={onCite} /></p>)}
  </div>;
}

export function Inline({ text, lookup, selected, onCite }) {
  return inlineTokens(text).map((token, index) => {
    if (token.type === "bold") return <strong key={index}>{token.value}</strong>;
    if (token.type === "code") return <code key={index}>{token.value}</code>;
    if (token.type === "ref") {
      const node = lookup ? resolveCitation(lookup, token.value) : null;
      if (!node) return <span key={index} className="cm-ref cm-ref--missing" title="Không có node này trong graph của luồng">{token.value}</span>;
      return <button key={index} type="button" className={`cm-ref${selected === node.node_id ? " cm-ref--sel" : ""}`} data-node={node.node_id}
        title={`${node.node_type} · ${node.node_id}`} onClick={(event) => { event.stopPropagation(); onCite?.(node.node_id); }}>{token.value}</button>;
    }
    return <React.Fragment key={index}>{token.value}</React.Fragment>;
  });
}

export function NodeRef({ id, name, selected, title, onClick, other }) {
  return <button type="button" className={`cm-ref${selected ? " cm-ref--sel" : ""}${other ? " cm-ref--other" : ""}`} data-node={id} title={title || id} onClick={onClick}>{name || id}</button>;
}

export function Kind({ icon, children }) {
  return <div className="cm-kind">{icon ? <md-icon>{icon}</md-icon> : null}{children}</div>;
}

export function downloadText(filename, text) {
  const type = filename.endsWith(".md") ? "text/markdown" : /\.ya?ml$/.test(filename) ? "text/yaml" : filename.endsWith(".json") ? "application/json" : "text/plain";
  const url = URL.createObjectURL(new Blob([text], { type: `${type};charset=utf-8` }));
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export async function copyText(text, element) {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    // Clipboard API refused (no permission, embedded browser): copy the selected text the older way.
    element?.focus();
    element?.select?.();
    try { return document.execCommand("copy"); } catch { return false; }
  }
}
