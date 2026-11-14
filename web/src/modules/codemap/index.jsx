// Code map page: loads the page config (packs, API bases) from /code-map/config, then runs the code-map app
// (App.jsx, its own views in the URL hash). Fills the window. API: viewer_hub/codemap/mount.py and codemap/api/.
import React from "react";
import "@xyflow/react/dist/style.css";
import "./codemap.css";
import { useLayout, useTitle } from "../../app/context.jsx";
import { http } from "../../app/http.js";
import { LinkButton, useLoad } from "../../app/ui.jsx";
import App from "./App.jsx";
import { config } from "./config.js";

export default function CodemapPage() {
  const { data } = useLoad(() => http.get(`/code-map/config${window.location.search}`));
  useTitle(data?.current ? `Code map · ${data.current}` : "Code map");
  useLayout(data?.config.pack ? "full" : "page");
  if (!data) return null;
  if (!data.config.pack) {
    return data.wanted ? <div className="md-empty">
      <md-icon>search_off</md-icon><h2>Không có pack “{data.wanted}”</h2>
      <p>Pack này không còn được bật hoặc không có thành phần code-map.</p>
      <LinkButton to="/code-map/" icon="account_tree">Mở pack mặc định</LinkButton>
    </div> : <div className="md-empty">
      <md-icon>account_tree</md-icon><h2>Chưa có dữ liệu code map</h2>
      <p>Import một pack <code>.sapack</code> có thành phần <code>codemap</code> trong Cài đặt, rồi bật pack đó.</p>
      <LinkButton to="/settings" icon="settings">Mở Cài đặt</LinkButton>
    </div>;
  }
  Object.assign(config, data.config);
  return <div className="cm-root"><App /></div>;
}
