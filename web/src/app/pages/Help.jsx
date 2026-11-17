// User guide (/help): HTML the server renders from its own guide files (help/parts + each module's GUIDE.md),
// never from user content, so it is inserted as HTML.
import React from "react";
import { useTitle } from "../context.jsx";
import { http } from "../http.js";
import { Skeleton, useLoad } from "../ui.jsx";

export default function Help() {
  const { data } = useLoad(() => http.get("/api/help"));
  useTitle(data?.title || "Hướng dẫn sử dụng");
  return <>
    {data ? <div className="md-help">
      <nav className="md-help__toc md-card md-card--outlined" aria-label="Mục lục" dangerouslySetInnerHTML={{ __html: data.toc }} />
      <article className="md-help__body" dangerouslySetInnerHTML={{ __html: data.html }} />
    </div> : <div className="md-help">
      <nav className="md-help__toc md-card md-card--outlined" style={{ padding: 16 }}><Skeleton count={6} /></nav>
      <article className="md-help__body" style={{ padding: 16 }}><Skeleton count={12} /></article>
    </div>}
  </>;
}
