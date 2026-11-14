import React, { useEffect, useMemo, useRef, useState } from "react";
import { IconButton } from "../../md/react.jsx";
import { ProgressBar } from "./common.jsx";

function allFlows(items) {
  return items.flatMap((item) => (item.kind === "flow" ? [item] : allFlows(item.children || [])));
}

export function ancestorsOf(menus, id) {
  const walk = (items, trail) => {
    for (const item of items) {
      if (item.id === id) return trail;
      const found = walk(item.children || [], [...trail, item.id]);
      if (found) return found;
    }
    return null;
  };
  return walk(menus || [], []) || [];
}

// Material Symbols per entry type (was lucide-react).
const FEATURE_ICONS = {
  API_OPERATION: "api", PROCEDURE: "data_object", FUNCTION: "data_object", TRIGGER: "bolt", SQL_FILE: "description", LOADER_CONTROL: "description",
  TABLE: "table", VIEW: "table", MATERIALIZED_VIEW: "table", UNRESOLVED_REFERENCE: "table",
  MESSAGE_TOPIC: "conversion_path", EXTERNAL_API_OPERATION: "conversion_path",
};

// Every menu and feature id below `items` (menus nest: system > group > section).
function containerIds(items) {
  return items.flatMap((item) => (item.kind === "flow" ? [] : [item.id, ...containerIds(item.children || [])]));
}

function countFeatures(items) {
  return items.reduce((sum, item) => sum + (item.kind === "feature" ? 1 : 0) + (item.kind === "menu" ? countFeatures(item.children || []) : 0), 0);
}

function iconOf(item) {
  if (item.kind === "menu") {
    if (item.unsorted) return "power";
    if (item.source === "system") return "dns";
    if (item.source === "group") return "folder";
    return "menu";
  }
  if (item.kind === "feature") return item.batch ? "schedule" : FEATURE_ICONS[item.entry_type] || "web_asset";
  if (item.kind === "entry") return "power";
  return "description";
}

export default function NavTree({ tree, selectedId, onSelect }) {
  const menus = tree?.menus || [];
  const [open, setOpen] = useState(() => new Set());
  const listRef = useRef(null);

  // Menus and features start open; the unassigned list starts closed.
  const initialized = useRef(false);
  useEffect(() => {
    if (initialized.current || !menus.length) return;
    initialized.current = true;
    setOpen(() => {
      const next = new Set();
      menus.forEach((menu) => {
        if (menu.unsorted) return;
        next.add(menu.id);
        (menu.children || []).forEach((child) => next.add(child.id));
      });
      return next;
    });
  }, [menus]);

  useEffect(() => {
    if (!selectedId) return;
    const trail = ancestorsOf(menus, selectedId);
    if (trail.some((id) => !open.has(id))) setOpen((current) => new Set([...current, ...trail]));
  }, [selectedId, menus]); // eslint-disable-line react-hooks/exhaustive-deps

  const rows = useMemo(() => {
    const result = [];
    const walk = (items, depth) => items.forEach((item) => {
      result.push({ item, depth });
      if ((item.children || []).length && open.has(item.id)) walk(item.children, depth + 1);
    });
    walk(menus, 0);
    return result;
  }, [menus, open]);

  const flows = useMemo(() => allFlows(menus), [menus]);
  const features = countFeatures(menus);

  function toggle(id) {
    setOpen((current) => {
      const next = new Set(current);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  }

  function onKeyDown(event) {
    const index = rows.findIndex((row) => row.item.id === selectedId);
    const row = rows[index];
    const go = (next) => { if (rows[next]) { onSelect(rows[next].item); focusRow(rows[next].item.id); } };
    if (event.key === "ArrowDown") go(index + 1);
    else if (event.key === "ArrowUp") go(Math.max(index - 1, 0));
    else if (event.key === "ArrowRight" && row?.item.children?.length && !open.has(row.item.id)) toggle(row.item.id);
    else if (event.key === "ArrowLeft" && row?.item.children?.length && open.has(row.item.id)) toggle(row.item.id);
    else if (event.key === "Enter" && row) onSelect(row.item, { open: true });
    else return;
    event.preventDefault();
  }

  // Roving tabindex: the selected row, or the first row when the selection is not in the visible tree.
  const tabStop = rows.some((row) => row.item.id === selectedId) ? selectedId : rows[0]?.item.id;

  function focusRow(id) {
    requestAnimationFrame(() => listRef.current?.querySelector(`[data-id="${CSS.escape(id)}"]`)?.focus());
  }

  const unsorted = menus.find((menu) => menu.unsorted);
  const hidden = unsorted && open.has(unsorted.id) ? (unsorted.total || 0) - unsorted.children.length : 0;
  return <nav className="cm-nav" aria-label="Menu và tính năng">
    <div className="cm-nav__head">
      <div className="cm-nav__title">
        <h2>Menu và tính năng</h2>
        <p>{menus.filter((menu) => !menu.unsorted).length} hệ thống · {features} tính năng · {flows.length} luồng</p>
      </div>
      {open.size
        ? <IconButton icon="unfold_less" label="Thu gọn tất cả" onClick={() => setOpen(new Set())} />
        : <IconButton icon="unfold_more" label="Mở tất cả" onClick={() => setOpen(new Set(containerIds(menus)))} />}
    </div>
    <ul className="cm-tree" role="tree" ref={listRef} onKeyDown={onKeyDown}>
      {rows.map(({ item, depth }) => {
        const hasChildren = Boolean(item.children?.length);
        const expanded = open.has(item.id);
        return <li key={item.id} data-id={item.id} role="treeitem" aria-level={depth + 1} aria-selected={item.id === selectedId}
          aria-expanded={hasChildren ? expanded : undefined} tabIndex={item.id === tabStop ? 0 : -1}
          className={`cm-tree__row cm-tree__row--${item.kind}${item.id === selectedId ? " is-selected" : ""}`} style={{ "--d": depth }}
          onClick={() => onSelect(item)}>
          {hasChildren
            ? <button type="button" tabIndex={-1} className="cm-tree__chev" aria-label={expanded ? "Thu gọn" : "Mở rộng"} onClick={(event) => { event.stopPropagation(); toggle(item.id); }}><md-icon>chevron_right</md-icon></button>
            : <span />}
          <md-icon class="cm-tree__icon">{iconOf(item)}</md-icon>
          <span className="cm-tree__name">{item.name}</span>
          <span className="cm-tree__meta">
            {item.questions ? <span className="cm-q">{item.questions} ?</span> : null}
            {item.kind === "flow" && !item.has_doc ? <span className="cm-nodoc">chưa viết</span> : null}
            {item.kind === "entry" ? <span className="cm-nodoc">chưa gán</span> : null}
            {(item.kind === "flow" && item.has_doc) || (item.kind !== "flow" && item.kind !== "entry" && !item.unsorted && item.parts?.length) ? <ProgressBar parts={item.parts} max={6} /> : null}
          </span>
        </li>;
      })}
      {hidden > 0 ? <li className="cm-tree__note">Còn {hidden} entry point chưa gán. Dùng ô tìm kiếm để tìm.</li> : null}
      {!rows.length ? <li className="cm-tree__note">Không có mục nào khớp bộ lọc.</li> : null}
    </ul>
  </nav>;
}
