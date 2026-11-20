// The open flow's data, in two places of the flow page (one request: GET /business/flows/<id>/data, business/data.py):
//  * FlowDataView: the stage's "Dữ liệu" view: the ERD of the tables the flow reads and writes, full size, each table
//    tagged with what the flow does to it (C/R/U/D); a table picked in the document is centred.
//  * FlowTables: the document's "Dữ liệu" section: those tables as a short list; a click shows the table in the ERD.
// The whole-database ERD is the "erd" addon ("Mở trong ERD" when it is installed, config.erdAddon).
import React, { useEffect, useMemo, useState } from "react";
import { businessApi } from "./api.js";
import { erdAddonUrl } from "./config.js";
import { ErdCanvas } from "./ErdCanvas.jsx";
import { Empty, ErrorBanner, Loading } from "../../md/react.jsx";

export const NAME_OPTIONS = [["ja", "日本語"], ["en", "English"], ["tech", "Kỹ thuật"]];
const OPS = { C: "tạo", R: "đọc", U: "sửa", D: "xoá" };
const NAMES_KEY = "viewer-hub.codemap.erd-names";

export function opsTitle(ops) {
  return ops.split("").map((letter) => OPS[letter] || letter).join(", ");
}

/** {data, error} of the flow's tables; `version` reloads after a link changes. */
export function useFlowData(flowId, version) {
  const [state, setState] = useState({ data: null, error: "" });
  useEffect(() => {
    let live = true;
    setState({ data: null, error: "" });
    businessApi.flowData(flowId).then((data) => { if (live) setState({ data, error: "" }); })
      .catch((reason) => { if (live) setState({ data: null, error: reason.message }); });
    return () => { live = false; };
  }, [flowId, version]);
  return state;
}

/** table id → the letters of every row (the flow, or each flow of a feature) merged, in C R U D order. */
export function tableOps(data) {
  const out = {};
  for (const table of data?.tables || []) {
    const letters = new Set((data.rows || []).flatMap((row) => (row.cells?.[table.id] || "").split("")));
    out[table.id] = "CRUD".split("").filter((letter) => letters.has(letter)).join("");
  }
  return out;
}

function readNames() {
  try { const value = localStorage.getItem(NAMES_KEY); return NAME_OPTIONS.some(([key]) => key === value) ? value : "ja"; } catch { return "ja"; }
}

/** [names, setNames]: which name the ERD shows (日本語 / English / Kỹ thuật), remembered on this machine. */
export function useErdNames() {
  const [names, setNamesState] = useState(readNames);
  const setNames = (value) => { setNamesState(value); try { localStorage.setItem(NAMES_KEY, value); } catch { /* ignore */ } };
  return [names, setNames];
}

/** The ERD addon link for the flow's tables and the tables linking to them; "" when the addon is not installed. */
export function erdLink(data) {
  if (!data?.tables?.length) return "";
  const tableIds = data.tables.filter((table) => table.node_type === "TABLE").map((table) => table.qualified_name || table.id);
  const outside = (data.erd?.outside || []).map((item) => item.qualified_name);
  return erdAddonUrl({ tables: [...tableIds, ...outside].join(",") });
}

export function FlowTables({ state, onShow }) {
  const { data, error } = state;
  const ops = useMemo(() => tableOps(data), [data]);
  if (error) return <ErrorBanner>{error}</ErrorBanner>;
  if (!data) return <Loading>Đang tìm bảng của luồng…</Loading>;
  if (!data.tables.length) {
    return <p className="md-muted">Luồng này không đọc hay ghi bảng nào. Nếu thật ra có, thêm liên kết tay (READS, INSERTS…) ở thẻ của node.</p>;
  }
  return <>
    <ul className="cm-tables">
      {data.tables.map((table) => <li key={table.id}>
        <button type="button" className="cm-tables__row" onClick={() => onShow(table.id)} title={`${table.qualified_name || table.name} · xem trong ERD bên phải`}>
          <md-icon aria-hidden="true">{table.node_type === "VIEW" ? "view_agenda" : "table"}</md-icon>
          <span className="cm-tables__name cm-mono">{table.name}</span>
          {table.manual ? <md-icon class="cm-tables__manual" title="Có liên kết tay">back_hand</md-icon> : null}
          <span className={`cm-tables__ops cm-mono${/[CUD]/.test(ops[table.id]) ? " is-write" : ""}`} title={opsTitle(ops[table.id] || "")}>{ops[table.id]}</span>
        </button>
      </li>)}
    </ul>
    {data.truncated ? <p className="md-muted cm-small">Luồng chạm {data.total} bảng; chỉ hiện {data.limit} bảng (bảng được ghi trước).</p> : null}
  </>;
}

export function FlowDataView({ state, names, focus, onFocus, onOpenNode }) {
  const { data, error } = state;
  const ops = useMemo(() => tableOps(data), [data]);
  if (error) return <div className="cm-stage__pad"><ErrorBanner>{error}</ErrorBanner></div>;
  if (!data) return <Loading>Đang vẽ ERD của luồng…</Loading>;
  if (!data.tables.length) {
    return <div className="cm-stage__pad"><Empty icon="database" title="Luồng này không đọc hay ghi bảng nào">
      Không có cạnh đọc / ghi tới bảng hay view. Nếu thật ra có, thêm liên kết tay (READS, INSERTS…) ở thẻ của node.
    </Empty></div>;
  }
  const model = data.erd;
  const openAll = erdLink(data);
  return <div className="cm-flowdata">
    {model ? <ErdCanvas model={model} names={names} tags={ops} focus={focus} onFocus={onFocus} onOpenNode={onOpenNode} />
      : <div className="cm-stage__pad"><p className="md-muted">Không có bảng (TABLE) nào để vẽ: luồng chỉ dùng view.</p></div>}
    <div className="cm-flowdata__foot md-body-small">
      {data.erd_error ? <span className="cm-error-text">{data.erd_error}</span> : null}
      {model && !model.has_fk_data ? <span className="md-muted">{model.message}</span> : null}
      {model?.outside_tables ? <span className="md-muted">{model.outside_tables} bảng khác có khoá ngoại tới các bảng này{openAll ? "" : " (cài addon ERD để xem cả cơ sở dữ liệu)"}.</span> : null}
      <span className="md-muted">C tạo · R đọc · U sửa · D xoá</span>
    </div>
  </div>;
}
