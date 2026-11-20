// The old whole-database ERD route (#/erd?table=…): the ERD browser is now the "erd" addon. Installed (and not
// locked): go there with the same table / schema / system; else say how to get it. Code map keeps only the ERD of
// the open flow (FlowData.jsx).
import React, { useEffect } from "react";
import { Empty } from "../../md/react.jsx";
import { LinkButton } from "../../app/ui.jsx";
import { erdAddonUrl } from "./config.js";

export default function ErdMoved({ params }) {
  const url = erdAddonUrl({ table: params.table || "", schema: params.schema || "", system: params.system || "" });
  useEffect(() => { if (url) window.location.replace(url); }, [url]);
  return <div className="cm-scroll"><div className="cm-page">
    {url ? <Empty icon="schema" title="Đang mở addon ERD…" /> : <Empty icon="schema" title="ERD cả cơ sở dữ liệu nay là addon ERD">
      Code map giờ chỉ vẽ ERD của các bảng một tính năng dùng: mở một tính năng rồi chọn tab <b>Dữ liệu</b>. Để duyệt cả cơ sở
      dữ liệu (chọn bảng, schema, xuất Mermaid / DBML), cài addon <b>ERD</b> ở Cài đặt → Addon (liên hệ admin nếu chưa có file).
      <div className="md-row" style={{ justifyContent: "center", marginTop: 16 }}><LinkButton to="/settings" icon="extension">Mở trang addon</LinkButton></div>
    </Empty>}
  </div></div>;
}
