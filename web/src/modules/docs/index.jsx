// Docs: markdown folders built into sites. /docs lists them, /docs/<id>/ shows one. API: viewer_hub/docs/routes.py.
import React, { useState } from "react";
import { Dialog } from "../../md/react.jsx";
import { useApp, useTitle } from "../../app/context.jsx";
import { http } from "../../app/http.js";
import { useRouter } from "../../app/router.jsx";
import { Badge, LinkButton, PageHeader, Skeleton, useAction, useLoad } from "../../app/ui.jsx";
import UploadDialog from "./UploadDialog.jsx";

const API = "/docs/api/sites";

export default function DocsPage({ subpath }) {
  const id = subpath.split("/").filter(Boolean)[0];
  return id ? <SiteDetail id={decodeURIComponent(id)} /> : <SiteList />;
}

function OpenButton({ site, variant = "tonal", label = "Mở" }) {
  if (!site.viewUrl) return null;
  const Tag = variant === "filled" ? "md-filled-button" : "md-filled-tonal-button";
  return <Tag href={site.viewUrl} target="_blank"><md-icon slot="icon">open_in_new</md-icon>{label}</Tag>;
}

function SiteBadges({ site, long }) {
  return <>
    {site.readonly ? <Badge tone="primary" icon="inventory_2">Data pack · {site.pack}{long ? " — do admin cung cấp, chỉ đọc" : ""}</Badge> : null}
    {site.buildError && !long ? <Badge tone="error" icon="error">Build lỗi</Badge> : null}
  </>;
}

function SiteList() {
  useTitle("Docs");
  const { app } = useApp();
  const { navigate } = useRouter();
  const { data } = useLoad(() => http.get(API));
  const [creating, setCreating] = useState(false);
  const create = <md-filled-button disabled={app.readonly || undefined} onClick={() => setCreating(true)}>
    <md-icon slot="icon">add</md-icon>Tạo site</md-filled-button>;
  return <>
    <PageHeader subtitle="Mỗi thư mục markdown thành một site có mục lục, tìm kiếm và giao diện Material.">{create}</PageHeader>
    {data && data.sites.length ? <div className="md-grid">
      {data.sites.map((site) => <article key={site.id} className="md-card md-card--outlined">
        <div className="md-card__body">
          <span className="md-card__icon"><md-icon>menu_book</md-icon></span>
          <h2 className="md-card__title">{site.title}</h2>
          <p className="md-card__subtitle">{site.pages} trang · {site.files} file</p>
          <SiteBadges site={site} />
        </div>
        <div className="md-card__actions">
          <md-text-button onClick={() => navigate(`/docs/${encodeURIComponent(site.id)}/`)}>Chi tiết</md-text-button>
          <OpenButton site={site} />
        </div>
      </article>)}
    </div> : data ? <div className="md-card md-card--outlined"><div className="md-empty">
      <md-icon>library_books</md-icon><h2>Chưa có site</h2>
      <p>Chọn một thư mục chứa file .md (hoặc file .zip). Nếu có <code>mkdocs.yml</code>, tên site và mục lục được lấy từ đó.</p>
      <md-filled-tonal-button disabled={app.readonly || undefined} onClick={() => setCreating(true)}>
        <md-icon slot="icon">create_new_folder</md-icon>Tạo site đầu tiên</md-filled-tonal-button>
    </div></div> : <div className="md-grid"><Skeleton count={3} height="120px" /></div>}
    {creating ? <UploadDialog onClose={() => setCreating(false)} onDone={(result) => navigate(`/docs/${encodeURIComponent(result.site.id)}/`)} /> : null}
  </>;
}

function SiteDetail({ id }) {
  useTitle("Docs");
  const { app } = useApp();
  const { navigate } = useRouter();
  const { data, error, reload } = useLoad(() => http.get(`${API}/${encodeURIComponent(id)}`), [id]);
  const [dialog, setDialog] = useState(null);
  const [run, busy] = useAction();
  if (error) return <div className="md-empty"><md-icon>search_off</md-icon><h2>{error.message}</h2>
    <LinkButton to="/docs/" icon="arrow_back">Về Docs</LinkButton></div>;
  if (!data) return <div className="md-stack" style={{ padding: 24 }}><Skeleton count={6} /></div>;
  const site = data.site;
  const disabled = app.readonly || busy || undefined;
  return <>
    <PageHeader title={site.title} subtitle={`${site.pages} trang · ${site.files} file nguồn`}>
      <md-text-button onClick={() => navigate("/docs/")}><md-icon slot="icon">arrow_back</md-icon>Docs</md-text-button>
      <OpenButton site={site} variant="filled" label="Mở site" />
    </PageHeader>
    <div className="md-stack">
      {site.buildError ? <div className="md-banner md-banner--error"><md-icon>error</md-icon>
        <div className="md-banner__text"><strong>Build lỗi.</strong> <code>{site.buildError}</code></div></div> : null}
      <section className="md-card md-card--outlined">
        <div className="md-card__body">
          <h2 className="md-card__title">Thông tin</h2>
          <div className="md-row"><Badge icon="schedule">Build: {site.builtAt || "chưa"}</Badge></div>
          {site.src ? <p className="md-card__subtitle">Nguồn: <code>{site.src}</code></p> : null}
        </div>
        {site.readonly ? <div className="md-card__body"><SiteBadges site={site} long /></div> : <div className="md-card__actions">
          <md-text-button disabled={disabled} onClick={() => setDialog("delete")}><md-icon slot="icon">delete</md-icon>Xoá</md-text-button>
          <md-outlined-button disabled={disabled} onClick={() => setDialog("upload")}><md-icon slot="icon">upload</md-icon>Cập nhật nguồn</md-outlined-button>
          <md-filled-tonal-button disabled={disabled} onClick={async () => {
            const result = await run(() => http.post(`${API}/${encodeURIComponent(site.id)}/rebuild`), (r) => r.message);
            if (result) reload();
          }}><md-icon slot="icon">refresh</md-icon>Build lại</md-filled-tonal-button>
        </div>}
      </section>
    </div>
    {dialog === "upload" ? <UploadDialog site={site} onClose={() => setDialog(null)} onDone={() => reload()} /> : null}
    {dialog === "delete" ? <Dialog className="md-dialog--danger" headline={`Xoá “${site.title}”?`} icon="delete" onClose={() => setDialog(null)}
      actions={(close) => <>
        <md-text-button onClick={close}>Huỷ</md-text-button>
        <md-filled-button class="md-button--danger" onClick={async () => {
          if (await run(() => http.delete(`${API}/${encodeURIComponent(site.id)}`), (r) => r.message)) navigate("/docs/");
          close();
        }}>Xoá</md-filled-button>
      </>}>
      File markdown và site đã build trong thư mục dữ liệu sẽ bị xoá. Không hoàn tác được.
    </Dialog> : null}
  </>;
}
