// Column settings: display name, description (AI reads it), shown, default filter, operator.
import React, { useState } from "react";
import { Checkbox, Dialog } from "../../md/react.jsx";
import { http } from "../../app/http.js";
import { useAction } from "../../app/ui.jsx";
import { API } from "./index.jsx";

export default function ColumnsDialog({ dataset, onClose, onSaved }) {
  const [columns, setColumns] = useState(dataset.columnList);
  const [run, busy] = useAction();
  const set = (key, patch) => setColumns(columns.map((c) => (c.key === key ? { ...c, ...patch } : c)));
  return <Dialog headline="Cấu hình cột" wide onClose={onClose}
    actions={(close) => <>
      <md-text-button onClick={close}>Huỷ</md-text-button>
      <md-filled-button disabled={busy || undefined} onClick={async () => {
        if (await run(() => http.put(`${API}/${encodeURIComponent(dataset.id)}/columns`, { columns }), (r) => r.message)) { close(); onSaved(); }
      }}>Lưu</md-filled-button>
    </>}>
    <div className="md-table-wrap" style={{ maxHeight: "55vh" }}>
      <table className="md-table">
        <thead><tr><th>Cột</th><th>Tên hiển thị</th><th title="AI đọc mô tả này">Mô tả</th><th>Hiện</th>
          <th title="Có sẵn một dòng lọc theo cột này khi mở trang">Lọc mặc định</th><th>Toán tử</th></tr></thead>
        <tbody>{columns.map((c) => <tr key={c.key}>
          <td title={c.type}>{c.name}</td>
          <td><input className="md-inline-input" value={c.label} placeholder={c.name} maxLength={120} onChange={(e) => set(c.key, { label: e.target.value })} /></td>
          <td><input className="md-inline-input" value={c.description} placeholder="Nghĩa của cột (tuỳ chọn)" maxLength={500} onChange={(e) => set(c.key, { description: e.target.value })} /></td>
          <td><Checkbox checked={c.visible} onChange={(visible) => set(c.key, { visible })} /></td>
          <td><Checkbox checked={c.filter} onChange={(filter) => set(c.key, { filter })} /></td>
          <td><select className="md-inline-select" value={c.op} onChange={(e) => set(c.key, { op: e.target.value })}>
            {dataset.operators.map((op) => <option key={op} value={op}>{op}</option>)}
          </select></td>
        </tr>)}</tbody>
      </table>
    </div>
  </Dialog>;
}
