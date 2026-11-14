// Name, description and "Cho AI đọc" of one dataset (the describe dialog after an upload and the edit dialog).
import React from "react";
import { Switch, TextField } from "../../md/react.jsx";

export default function InfoFields({ dataset, value, onChange }) {
  const set = (key) => (next) => onChange({ ...value, [key]: next });
  return <div className="csv-info">
    <span className="csv-info__file"><md-icon>table_view</md-icon>{dataset.file} · {dataset.rows.toLocaleString()} dòng · {dataset.columns} cột</span>
    <TextField label="Tên" value={value.title} onChange={set("title")} maxLength={120} />
    <TextField label="Mô tả (cho người xem và AI)" type="textarea" rows={2} value={value.description} onChange={set("description")} maxLength={2000}
      supportingText="File này là gì, mỗi dòng là gì. Ví dụ: Từ điển cột của DB đơn hàng — mỗi dòng là một cột của một bảng" />
    <Switch selected={value.mcp} onChange={set("mcp")} title="AI agent (Copilot, Claude) đọc được file này">
      Cho AI đọc · chỉ bật khi file không có dữ liệu nhạy cảm</Switch>
  </div>;
}

export const infoOf = (dataset) => ({ title: dataset.title, description: dataset.description, mcp: dataset.mcp });
