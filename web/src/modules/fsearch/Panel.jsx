// "Nâng cao": language, dates, grouping, page size, OR/AND, word distance, exact modes; local file root.
import React, { useEffect, useRef, useState } from "react";
import { Chip, Select, Switch, TextField } from "../../md/react.jsx";
import { http } from "../../app/http.js";

export function advancedCount(params) {
  return [params.get("lang"), params.get("date_from"), params.get("date_to"), params.get("op") === "AND",
    params.get("phrase") === "1", params.get("exact") === "1", !["", "0", null].includes(params.get("proximity")),
    params.get("group_by")].filter(Boolean).length;
}

function Slider({ value, onChange }) {
  const ref = useRef(null);
  useEffect(() => { if (ref.current) ref.current.value = value; }, [value]);
  useEffect(() => {
    const element = ref.current;
    const listener = () => onChange(Number(element.value));
    element?.addEventListener("input", listener);
    return () => element?.removeEventListener("input", listener);
  });
  return <md-slider ref={ref} min="0" max="20" labeled style={{ width: "100%" }}></md-slider>;
}

export default function Panel({ params, data, onApply, onReset }) {
  const { options } = data;
  const [draft, setDraft] = useState(() => ({
    pack: params.get("pack") || data.source, lang: params.get("lang") || "", date_from: params.get("date_from") || "",
    date_to: params.get("date_to") || "", group_by: params.get("group_by") || "", rows: params.get("rows") || "10",
    op: params.get("op") === "AND" ? "AND" : "OR", proximity: Number(params.get("proximity") || 0),
    phrase: params.get("phrase") === "1", exact: params.get("exact") === "1", debug: params.get("debug") === "1",
  }));
  const [root, setRoot] = useState(data.localRoot);
  const set = (key) => (value) => setDraft({ ...draft, [key]: value });
  const apply = () => onApply({
    pack: data.sources.length > 1 ? draft.pack : null, lang: draft.lang, date_from: draft.date_from, date_to: draft.date_to,
    group_by: draft.group_by, rows: draft.rows === "10" ? null : draft.rows, op: draft.op === "AND" ? "AND" : null,
    proximity: draft.proximity || null, phrase: draft.phrase ? "1" : null, exact: draft.exact ? "1" : null, debug: draft.debug ? "1" : null,
  });
  const saveRoot = async () => {
    try {
      const result = await http.post("/ocr-search/api/local-root", { path: root.trim() });
      window.md?.snackbar(result.path ? "Đã lưu thư mục file gốc" : "Đã tắt mở file");
      apply();
    } catch (error) {
      window.md?.snackbar(error.message);
    }
  };
  return <section className="md-filter-panel" aria-label="Tìm nâng cao">
    <div className="md-filter-panel__grid">
      {data.sources.length > 1 ? <Select label="Nguồn" value={draft.pack} options={data.sources.map((s) => [s.id, s.title])} onChange={set("pack")} /> : null}
      <Select label="Ngôn ngữ" value={draft.lang} options={options.languages} onChange={set("lang")} />
      <TextField type="date" label="Từ ngày" value={draft.date_from} onChange={set("date_from")} />
      <TextField type="date" label="Đến ngày" value={draft.date_to} onChange={set("date_to")} />
      <Select label="Nhóm theo" value={draft.group_by} options={options.group} onChange={set("group_by")} />
      <Select label="Kết quả mỗi trang" value={draft.rows} options={["10", "20", "50", "100"].map((n) => [n, n])} onChange={set("rows")} />
      <div>
        <h3>Kết hợp từ khoá</h3>
        <md-chip-set>
          <Chip selected={draft.op === "OR"} onClick={() => set("op")("OR")}>OR · bất kỳ</Chip>
          <Chip selected={draft.op === "AND"} onClick={() => set("op")("AND")}>AND · tất cả</Chip>
        </md-chip-set>
      </div>
      <div>
        <h3>Khoảng cách từ: {draft.proximity}</h3>
        <Slider value={draft.proximity} onChange={set("proximity")} />
      </div>
      <div className="md-stack" style={{ gap: 8 }}>
        <Switch selected={draft.phrase} onChange={set("phrase")}>Cụm từ chính xác</Switch>
        <Switch selected={draft.exact} onChange={set("exact")}>Từng từ chính xác</Switch>
        <Switch selected={draft.debug} onChange={set("debug")}>Debug truy vấn</Switch>
      </div>
      <div className="md-filter-panel__wide">
        <h3>Thư mục file gốc (mở file trên máy)</h3>
        <div className="md-row">
          <div style={{ flex: 1 }}><TextField label="Đường dẫn · để trống để tắt" value={root} onChange={setRoot} /></div>
          <md-outlined-button onClick={saveRoot}><md-icon slot="icon">save</md-icon>Lưu</md-outlined-button>
        </div>
      </div>
    </div>
    <div className="md-filter-panel__actions">
      <md-text-button onClick={onReset}>Đặt lại</md-text-button>
      <md-filled-button onClick={apply}><md-icon slot="icon">check</md-icon>Áp dụng</md-filled-button>
    </div>
  </section>;
}
