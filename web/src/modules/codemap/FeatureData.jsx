// "Dữ liệu" view of the open flow: the tables it reads and writes (hand-made links included), its CRUD row and the
// ERD of those tables. API: GET /business/flows/<id>/data (business/data.py; a feature id gives one row per flow).
// The whole-database ERD is the "erd" addon: "Mở trong ERD" when it is installed (config.erdAddon).
import React, { useEffect, useState } from "react";
import { businessApi } from "./api.js";
import { erdAddonUrl } from "./config.js";
import { ErdCanvas } from "./ErdCanvas.jsx";
import { Button, Empty, ErrorBanner, Loading, Segmented } from "../../md/react.jsx";

const NAME_OPTIONS = [["ja", "日本語"], ["en", "English"], ["tech", "Tên kỹ thuật"]];
const OPS = { C: "Tạo", R: "Đọc", U: "Sửa", D: "Xoá" };

function opsTitle(ops) {
  return ops.split("").map((letter) => OPS[letter] || letter).join(", ");
}

function CrudMatrix({ data, onOpenNode }) {
  return <div className="md-table-wrap cm-crud">
    <table className="md-table">
      <thead><tr>
        <th scope="col">Luồng</th>
        {data.tables.map((table) => <th key={table.id} scope="col" className="cm-crud__table" title={table.qualified_name}>
          <button type="button" className="cm-crud__name cm-mono" onClick={() => onOpenNode(table.id)}>{table.name}</button>
          {table.manual ? <md-icon class="cm-crud__manual" title="Có liên kết tay">back_hand</md-icon> : null}
        </th>)}
      </tr></thead>
      <tbody>{data.rows.map((row) => <tr key={row.id}>
        <th scope="row" className={row.kind === "feature" ? "md-muted" : ""}>{row.name}</th>
        {data.tables.map((table) => {
          const ops = row.cells[table.id] || "";
          return <td key={table.id} className={`cm-crud__cell${/[CUD]/.test(ops) ? " is-write" : ""}`} title={ops ? opsTitle(ops) : undefined}>
            <span className="cm-mono">{ops}</span></td>;
        })}
      </tr>)}</tbody>
    </table>
  </div>;
}

export default function FeatureData({ featureId, flowId, onOpenNode }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  const [names, setNames] = useState("ja");
  useEffect(() => {
    let live = true;
    setData(null);
    setError("");
    (flowId ? businessApi.flowData(flowId) : businessApi.featureData(featureId))
      .then((body) => { if (live) setData(body); }).catch((reason) => { if (live) setError(reason.message); });
    return () => { live = false; };
  }, [featureId, flowId]);
  const what = flowId ? "luồng" : "tính năng";
  if (error) return <ErrorBanner>{error}</ErrorBanner>;
  if (!data) return <Loading>Đang tìm bảng của {what}…</Loading>;
  if (!data.tables.length) {
    return <Empty icon="database" title={`${flowId ? "Luồng" : "Tính năng"} này không đọc hay ghi bảng nào`}>
      Không có cạnh đọc / ghi tới bảng hay view. Nếu thật ra có, thêm liên kết tay (READS, INSERTS…) ở thẻ của node.
    </Empty>;
  }
  const model = data.erd;
  const tableIds = data.tables.filter((table) => table.node_type === "TABLE").map((table) => table.qualified_name || table.id);
  const openAll = erdAddonUrl({ tables: tableIds.join(",") });
  return <div className="cm-data">
    <div className="cm-data__bar">
      <span className="md-muted">{data.tables.length} bảng · {data.rows.length} dòng{data.truncated ? ` · ẩn ${data.omitted} bảng (tối đa ${data.limit})` : ""}</span>
      <span className="md-spacer" />
      <Segmented label="Tên hiển thị" options={NAME_OPTIONS} value={names} onChange={setNames} dense />
      {openAll ? <Button variant="tonal" icon="schema" onClick={() => { window.location.href = openAll; }}>Mở trong ERD</Button> : null}
    </div>
    {data.truncated ? <p className="md-muted cm-small">{flowId ? "Luồng" : "Tính năng"} chạm {data.total} bảng; chỉ hiện {data.limit} bảng (bảng được ghi trước, rồi bảng nhiều luồng dùng).</p> : null}
    <section className="cm-list">
      <span className="cm-label">Ma trận CRUD (C tạo · R đọc · U sửa · D xoá)</span>
      <CrudMatrix data={data} onOpenNode={onOpenNode} />
    </section>
    <section className="cm-list">
      <span className="cm-label">Quan hệ giữa các bảng (khoá ngoại)</span>
      {data.erd_error ? <ErrorBanner>{data.erd_error}</ErrorBanner> : null}
      {model && !model.has_fk_data ? <p className="md-muted cm-small">{model.message}</p> : null}
      {model ? <div className="cm-data__erd">
        <ErdCanvas model={model} names={names} onOpenNode={onOpenNode}
          onFocus={(id) => { const url = erdAddonUrl({ table: id }); if (url) window.location.href = url; }} />
      </div> : <p className="md-muted cm-small">Không có bảng (TABLE) nào để vẽ: các mục trên là view.</p>}
      {model?.outside_tables ? <div className="cm-data__outside">
        {erdAddonUrl() ? <button type="button" className="cm-erd-link"
          onClick={() => { window.location.href = erdAddonUrl({ tables: [...tableIds, ...(model.outside || []).map((item) => item.qualified_name)].join(",") }); }}>
          <md-icon>more_horiz</md-icon>{model.outside_tables} bảng khác có khoá ngoại tới các bảng này</button>
          : <span className="md-muted cm-small">{model.outside_tables} bảng khác có khoá ngoại tới các bảng này (cài addon ERD để xem cả cơ sở dữ liệu).</span>}
      </div> : null}
    </section>
  </div>;
}
