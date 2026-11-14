import React, { useEffect, useRef, useState } from "react";
import { businessApi } from "./api.js";
import { typeLabel } from "./lib/text.js";

const GROUPS = [
  ["feature", "Menu & tính năng", "web_asset"],
  ["flow", "Luồng nghiệp vụ", "route"],
  ["step", "Bước", "format_list_numbered"],
  ["rule", "Quy tắc", "rule"],
  ["node", "Node trong code", "deployed_code"],
];

// M3 search bar with a results menu; "/" focuses it.
export default function SearchBox({ onPick }) {
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(false);
  const [results, setResults] = useState([]);
  const [state, setState] = useState({ loading: false, error: "" });
  const [active, setActive] = useState(0);
  const input = useRef(null);
  const box = useRef(null);

  useEffect(() => {
    const term = query.trim();
    if (!term) { setResults([]); return undefined; }
    const controller = new AbortController();
    const timer = setTimeout(async () => {
      setState({ loading: true, error: "" });
      try {
        const body = await businessApi.search(term, controller.signal);
        const business = (body.business || []).map((hit) => ({ ...hit, group: hit.kind === "menu" ? "feature" : hit.kind }));
        const nodes = (body.nodes || []).map((hit) => ({ ...hit, group: "node" }));
        setResults([...business, ...nodes]);
        setActive(0);
        setState({ loading: false, error: "" });
      } catch (error) {
        if (error.name !== "AbortError") setState({ loading: false, error: error.message });
      }
    }, 180);
    return () => { clearTimeout(timer); controller.abort(); };
  }, [query]);

  useEffect(() => {
    const onKey = (event) => {
      if (event.key === "/" && !event.composedPath().some((el) => el instanceof Element && el.matches?.("input, textarea, select"))) {
        event.preventDefault(); input.current?.focus();
      }
    };
    const onClick = (event) => { if (!box.current?.contains(event.target)) setOpen(false); };
    window.addEventListener("keydown", onKey);
    document.addEventListener("mousedown", onClick);
    return () => { window.removeEventListener("keydown", onKey); document.removeEventListener("mousedown", onClick); };
  }, []);

  const ordered = GROUPS.flatMap(([group]) => results.filter((hit) => hit.group === group));

  function pick(hit) {
    if (!hit) return;
    setOpen(false);
    input.current?.blur();
    onPick(hit);
  }

  function onKeyDown(event) {
    if (event.key === "ArrowDown") { setActive((value) => Math.min(value + 1, ordered.length - 1)); event.preventDefault(); }
    else if (event.key === "ArrowUp") { setActive((value) => Math.max(value - 1, 0)); event.preventDefault(); }
    else if (event.key === "Enter") { pick(ordered[active]); event.preventDefault(); }
    else if (event.key === "Escape") { setOpen(false); input.current?.blur(); }
  }

  let position = -1;
  return <div className="cm-search" ref={box}>
    <div className="md-search-bar cm-search__bar">
      <md-icon>search</md-icon>
      <input ref={input} type="search" value={query} autoComplete="off" spellCheck={false} aria-label="Tìm kiếm" role="combobox" aria-expanded={open && Boolean(query.trim())}
        placeholder="Tìm nghiệp vụ, bước, quy tắc, method, API, bảng… (/)"
        onChange={(event) => { setQuery(event.target.value); setOpen(true); }} onFocus={() => setOpen(true)} onKeyDown={onKeyDown} />
      <md-icon-button class="md-search-bar__clear" aria-label="Xoá nội dung tìm" hidden={!query || undefined}
        onClick={() => { setQuery(""); input.current?.focus(); }}><md-icon>close</md-icon></md-icon-button>
      <md-filled-icon-button class="md-search-bar__submit" aria-label="Tìm" title="Mở kết quả đang chọn (Enter)"
        onClick={() => { if (ordered[active]) pick(ordered[active]); else { setOpen(true); input.current?.focus(); } }}><md-icon>search</md-icon></md-filled-icon-button>
    </div>
    {open && query.trim() ? <div className="cm-search__menu" role="listbox">
      {state.loading ? <md-linear-progress indeterminate /> : null}
      {state.error ? <p className="cm-search__empty">{state.error}</p> : null}
      {!state.error && !ordered.length ? <p className="cm-search__empty">{state.loading ? "Đang tìm…" : `Không có kết quả cho “${query}”.`}</p> : null}
      {GROUPS.map(([group, title, icon]) => {
        const hits = results.filter((hit) => hit.group === group);
        if (!hits.length) return null;
        return <React.Fragment key={group}>
          <h6 className="cm-search__group">{title}</h6>
          {hits.map((hit) => {
            position += 1;
            const index = position;
            return <button key={`${hit.group}:${hit.id}:${hit.step_id || ""}:${index}`} type="button" role="option" aria-selected={index === active}
              className={`cm-hit${index === active ? " is-active" : ""}`} onMouseEnter={() => setActive(index)} onClick={() => pick(hit)}>
              <span className="cm-hit__icon">{hit.group === "node" ? <span className="cm-hit__type">{hit.node_type.slice(0, 2)}</span> : <md-icon>{icon}</md-icon>}</span>
              <span className="cm-hit__text"><b className={hit.group === "node" ? "cm-mono" : ""}>{hit.label}</b>
                <small>{hit.group === "node" ? [typeLabel(hit.node_type), hit.path || "chưa thuộc tính năng nào"].join(" · ") : hit.path || hit.route || ""}</small></span>
            </button>;
          })}
        </React.Fragment>;
      })}
    </div> : null}
  </div>;
}
