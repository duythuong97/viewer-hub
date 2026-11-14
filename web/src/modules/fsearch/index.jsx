// F-Search: full-text search over the active packs. The URL query is the state (old bookmarks keep working);
// every change of a picker or the panel's Áp dụng navigates, and the page fetches /ocr-search/api/search with it.
import React, { useEffect, useState } from "react";
import { InputChip, Select } from "../../md/react.jsx";
import { useLayout, useTitle } from "../../app/context.jsx";
import { http } from "../../app/http.js";
import { useRouter } from "../../app/router.jsx";
import { SearchBar, useLoad } from "../../app/ui.jsx";
import Panel, { advancedCount } from "./Panel.jsx";
import Results from "./Results.jsx";

const BASE = "/ocr-search/search";

export default function FsearchPage() {
  const { search, navigate } = useRouter();
  const params = new URLSearchParams(search);
  const query = params.get("q") || "";
  useTitle("F-Search");
  useLayout("wide");
  const { data } = useLoad(() => fetch(`/ocr-search/api/search${search}`, { headers: { Accept: "application/json" } })
    .then((r) => r.json()), [search]);
  const [panel, setPanel] = useState(() => { try { return localStorage.getItem("viewer-hub.filters.fsearch") === "1"; } catch { return false; } });
  useEffect(() => { try { localStorage.setItem("viewer-hub.filters.fsearch", panel ? "1" : "0"); } catch { /* blocked */ } }, [panel]);
  useEffect(() => {
    const onKey = (event) => {
      if (event.key === "/" && !event.target.closest?.("input, textarea, md-outlined-text-field")) {
        event.preventDefault();
        document.querySelector(".md-search-bar input")?.focus();
      }
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, []);

  /** Navigate with some parameters changed (null removes); any change but the page number goes back to page 1. */
  const go = (changes) => {
    const next = new URLSearchParams(search);
    for (const [key, value] of Object.entries(changes)) {
      next.delete(key);
      for (const item of [].concat(value ?? [])) if (item !== "" && item !== null && item !== false) next.append(key, String(item));
    }
    if (!("page" in changes)) next.delete("page");
    navigate(`${BASE}?${next}`);
  };

  if (!data) return null;
  if (!data.sources.length) return <div className="md-card md-card--outlined"><div className="md-empty">
    <md-icon>manage_search</md-icon><h2>Chưa có dữ liệu tìm kiếm</h2>
    <p>Import một data pack có <code>search/search.sqlite</code>.<br />Trên máy tác giả: <code>viewer-hub export-solr http://localhost:8983/solr/documents --out search.sqlite</code></p>
  </div></div>;

  const { options, facets } = data;
  const many = (key) => params.getAll(key).flatMap((v) => v.split(",")).filter(Boolean);
  const pickerValue = (key) => (many(key).length === 1 ? many(key)[0] : "");
  const picker = (key, label) => <Select key={key} label={label} className="md-select--compact" value={pickerValue(key)}
    options={[["", "Tất cả"], ...(facets[key] || []).map(([value, count]) => [value, `${value} · ${Number(count).toLocaleString()}`])]}
    onChange={(value) => go({ [key]: value || null })} />;
  const n = advancedCount(params);
  const label = (list, value) => (list.find(([v]) => v === value) || [, value])[1];
  const chips = [
    ...(many("repository").length > 1 ? many("repository").map((v) => [`Repository: ${v}`, { repository: many("repository").filter((x) => x !== v) }]) : []),
    ...(many("file_type").length > 1 ? many("file_type").map((v) => [`Loại: ${v}`, { file_type: many("file_type").filter((x) => x !== v) }]) : []),
    params.get("lang") && [`Ngôn ngữ: ${label(options.languages, params.get("lang"))}`, { lang: null }],
    params.get("date_from") && [`Từ ${params.get("date_from")}`, { date_from: null }],
    params.get("date_to") && [`Đến ${params.get("date_to")}`, { date_to: null }],
    params.get("op") === "AND" && ["AND · tất cả từ", { op: null }],
    params.get("phrase") === "1" && ["Cụm từ chính xác", { phrase: null }],
    params.get("exact") === "1" && ["Từng từ chính xác", { exact: null }],
    !["", "0", null].includes(params.get("proximity")) && [`Khoảng cách ≤ ${params.get("proximity")}`, { proximity: null }],
    params.get("group_by") && [`Nhóm: ${label(options.group, params.get("group_by"))}`, { group_by: null }],
  ].filter(Boolean);
  const result = data.search;

  return <div className="md-stack">
    {/* One toolbar row: the search box, the filters people use most, everything else behind "Nâng cao". */}
    <div className="md-search-toolbar">
      <div className="md-search-toolbar__search">
        <SearchBar value={query} autoFocus placeholder={'Tìm trong tài liệu, code, OCR…  (-từ để loại trừ, "cụm từ")'}
          onSubmit={(q) => go({ q })} />
      </div>
      <div className="md-search-toolbar__filters">
        {picker("repository", "Repository")}
        {picker("file_type", "Loại file")}
        <Select label="Sắp xếp" className="md-select--compact" value={params.get("sort") || "score desc"} options={options.sort}
          onChange={(sort) => go({ sort })} />
        <md-outlined-button aria-expanded={panel ? "true" : "false"} data-open={panel ? "" : undefined} onClick={() => setPanel(!panel)}>
          <md-icon slot="icon">tune</md-icon>Nâng cao{n ? ` · ${n}` : ""}</md-outlined-button>
      </div>
    </div>

    {chips.length || (result && !result.error) ? <div className="md-filter-bar">
      <md-chip-set class="md-filter-bar__chips">
        {chips.map(([text, change]) => <InputChip key={text} label={text} onRemove={() => go(change)} />)}
      </md-chip-set>
      {result && !result.error ? <span className="md-filter-bar__summary">
        {result.numFound.toLocaleString()} {result.grouped ? "nhóm" : "kết quả"}{result.totalPages > 1 ? ` · trang ${result.page}/${result.totalPages}` : ""}
      </span> : null}
    </div> : null}

    {panel ? <Panel params={params} data={data} onApply={(changes) => go(changes)} onReset={() => navigate("/ocr-search/")} /> : null}

    <section aria-live="polite">
      {result ? <Results result={result} debug={params.get("debug") === "1"} onPage={(page) => go({ page })} />
        : <div className="md-empty"><md-icon>travel_explore</md-icon><h2>Nhập từ khoá để tìm</h2>
          <p>Tìm trong {data.sources.length} nguồn dữ liệu. Hỗ trợ tiếng Anh, tiếng Việt (không dấu vẫn tìm được) và tiếng Nhật.</p></div>}
    </section>
  </div>;
}
