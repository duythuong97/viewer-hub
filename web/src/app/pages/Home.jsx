// Home: one card per module (from the registry, with its count when it has one), then the active data packs.
import React from "react";
import { useApp, useTitle } from "../context.jsx";
import { http } from "../http.js";
import { Link } from "../router.jsx";
import { LinkCard, ListItem, PageHeader, Skeleton, useLoad } from "../ui.jsx";

export default function Home() {
  useTitle("Viewer Hub");
  const { app } = useApp();
  const { data } = useLoad(() => http.get("/api/home"));
  const stats = data?.stats || {};
  return <>
    <PageHeader title="Xin chào" subtitle="Mọi dữ liệu và công cụ của bạn, chạy ngay trên máy này." />
    {data?.alerts?.length ? <div className="md-banner md-banner--error" role="alert">
      <md-icon>monitoring</md-icon>
      <div className="md-banner__text">Giám sát: {data.alerts.slice(0, 2).map((x) => `${x.label}: ${x.message}`).join("; ")}
        {data.alerts.length > 2 ? ` (và ${data.alerts.length - 2} cảnh báo khác)` : ""}</div>
      <Link to="/monitor"><md-text-button>Xem</md-text-button></Link>
    </div> : null}
    <div className="md-grid">
      {app.nav.filter((item) => item.module).map((item) => <LinkCard key={item.key} to={item.path} icon={item.icon} title={item.label}>
        {stats[item.key] ? `${stats[item.key]}. ` : ""}{item.summary}
      </LinkCard>)}
    </div>
    <h2 className="md-section-title">Data pack</h2>
    <div className="md-card md-card--outlined">
      {data && data.packs.length ? <ul className="md-list">
        {data.packs.map((pack) => <ListItem key={pack.id} icon="inventory_2" headline={pack.title} supporting={`${pack.id} · ${pack.version}`} />)}
      </ul> : data ? <div className="md-empty">
        <md-icon>inventory_2</md-icon><h2>Chưa có data pack</h2>
        <p>Import file <code>.sapack</code> trong <Link to="/settings">Cài đặt</Link>.</p>
      </div> : <div style={{ padding: 16 }}><Skeleton count={3} /></div>}
    </div>
  </>;
}
