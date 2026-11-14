// Source file viewer (/api/graph/snippet). Only offered when the pack ships source/ (config.source).
import React, { useEffect, useRef, useState } from "react";
import { businessApi } from "./api.js";
import { Dialog, ErrorBanner, Loading } from "../../md/react.jsx";

const MESSAGES = {
  source_unavailable: "Pack này không kèm file nguồn.",
  invalid_source: "Không mở được file này (ngoài thư mục source hoặc không có bằng chứng trong graph).",
  not_found: "Không thấy file trong source của pack.",
  unreadable: "Không đọc được file.",
};

export default function SnippetDialog({ path, targetId, onClose }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  const focus = useRef(null);

  useEffect(() => {
    let live = true;
    businessApi.snippet(path, targetId)
      .then((body) => { if (live) { if (body.status === "available") setData(body); else setError(MESSAGES[body.status] || body.status); } })
      .catch((reason) => { if (live) setError(MESSAGES[reason.body?.status] || reason.message); });
    return () => { live = false; };
  }, [path, targetId]);

  useEffect(() => { focus.current?.scrollIntoView({ block: "center" }); }, [data]);

  const lines = String(data?.content || "").split("\n");
  const start = data?.start_line || data?.focus_line || 0;
  const end = data?.end_line || start;
  return <Dialog headline={path} icon="code" wide onClose={onClose}>
    {error ? <ErrorBanner>{error}</ErrorBanner> : !data ? <Loading /> : <pre className="cm-snippet">
      {lines.map((line, index) => {
        const number = index + 1;
        const hit = number >= start && number <= end;
        return <span key={index} ref={number === start ? focus : null} className={`cm-snippet__line${hit ? " cm-snippet__line--hit" : ""}`}>
          <span className="cm-snippet__no">{number}</span>{line || " "}{"\n"}
        </span>;
      })}
    </pre>}
  </Dialog>;
}
