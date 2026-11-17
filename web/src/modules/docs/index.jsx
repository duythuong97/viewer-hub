// Docs: markdown folders built into sites. /docs lists them, details open in a dialog. API: viewer_hub/docs/routes.py.
import React, { useEffect, useState } from "react";
import { Dialog } from "../../md/react.jsx";
import { useApp, useTitle } from "../../app/context.jsx";
import { http } from "../../app/http.js";
import { useRouter } from "../../app/router.jsx";
import { Badge, PageHeader, Skeleton, useAction, useLoad } from "../../app/ui.jsx";
import UploadDialog from "./UploadDialog.jsx";

const API = "/docs/api/sites";

export default function DocsPage({ subpath }) {
  const id = subpath.split("/").filter(Boolean)[0];
  return <SiteList selectedId={id ? decodeURIComponent(id) : null} />;
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

function SiteList({ selectedId }) {
  useTitle("Docs");
  const { app } = useApp();
  const { navigate } = useRouter();
  const { data, reload } = useLoad(() => http.get(API));
  const [uploadTarget, setUploadTarget] = useState(null);
  const [detailSite, setDetailSite] = useState(null);
  const [deleting, setDeleting] = useState(null);
  const [run, busy] = useAction();

  useEffect(() => {
    if (selectedId && data?.sites) {
      const match = data.sites.find((s) => s.id === selectedId);
      if (match) setDetailSite(match);
    }
  }, [selectedId, data]);

  const closeDetail = () => {
    setDetailSite(null);
    if (selectedId) navigate("/docs/", { replace: true });
  };

  const create = <md-filled-button disabled={app.readonly || undefined} onClick={() => setUploadTarget("new")}>
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
          {!site.readonly ? <md-text-button disabled={app.readonly || busy || undefined} onClick={() => setDeleting(site)}>
            <md-icon slot="icon">delete</md-icon>Xoá
          </md-text-button> : null}
          <md-text-button onClick={() => setDetailSite(site)}>Chi tiết</md-text-button>
          <OpenButton site={site} />
        </div>
      </article>)}
    </div> : data ? <div className="md-card md-card--outlined"><div className="md-empty">
      <md-icon>library_books</md-icon><h2>Chưa có site</h2>
      <p>Chọn một thư mục chứa file .md (hoặc file .zip). Nếu có <code>mkdocs.yml</code>, tên site và mục lục được lấy từ đó.</p>
      <md-filled-tonal-button disabled={app.readonly || undefined} onClick={() => setUploadTarget("new")}>
        <md-icon slot="icon">create_new_folder</md-icon>Tạo site đầu tiên</md-filled-tonal-button>
    </div></div> : <div className="md-grid"><Skeleton count={3} height="120px" /></div>}

    {uploadTarget ? <UploadDialog
      site={uploadTarget === "new" ? null : uploadTarget}
      onClose={() => setUploadTarget(null)}
      onDone={(result) => {
        setUploadTarget(null);
        reload();
        if (detailSite && result?.site) setDetailSite(result.site);
      }}
    /> : null}

    {detailSite ? <DetailDialog
      site={detailSite}
      onClose={closeDetail}
      onRebuilt={(updated) => {
        setDetailSite(updated);
        reload();
      }}
      onUpload={(s) => setUploadTarget(s)}
      onDelete={(s) => setDeleting(s)}
    /> : null}

    {deleting ? <Dialog className="md-dialog--danger" headline={`Xoá “${deleting.title}”?`} icon="delete" onClose={() => setDeleting(null)}
      actions={(close) => <>
        <md-text-button onClick={close}>Huỷ</md-text-button>
        <md-filled-button class="md-button--danger" disabled={busy || undefined} onClick={async () => {
          if (await run(() => http.delete(`${API}/${encodeURIComponent(deleting.id)}`), (r) => r.message)) {
            if (detailSite?.id === deleting.id) closeDetail();
            reload();
          }
          close();
        }}>Xoá</md-filled-button>
      </>}>
      File markdown và site đã build trong thư mục dữ liệu sẽ bị xoá. Không hoàn tác được.
    </Dialog> : null}
  </>;
}

function DetailDialog({ site, onClose, onRebuilt, onUpload, onDelete }) {
  const { app } = useApp();
  const [run, busy] = useAction();
  const disabled = app.readonly || busy || undefined;

  return <Dialog headline={site.title} icon="menu_book" onClose={onClose}
    actions={(close) => <>
      <md-text-button onClick={close}>Đóng</md-text-button>
      {!site.readonly ? <md-text-button disabled={disabled} onClick={() => { close(); onDelete(site); }}>
        <md-icon slot="icon">delete</md-icon>Xoá
      </md-text-button> : null}
      {!site.readonly ? <md-outlined-button disabled={disabled} onClick={() => { close(); onUpload(site); }}>
        <md-icon slot="icon">upload</md-icon>Cập nhật nguồn
      </md-outlined-button> : null}
      {!site.readonly ? <md-filled-tonal-button disabled={disabled} onClick={async () => {
        const result = await run(() => http.post(`${API}/${encodeURIComponent(site.id)}/rebuild`), (r) => r.message);
        if (result) onRebuilt?.(result.site);
      }}>
        {busy ? <md-circular-progress indeterminate slot="icon" style={{ width: 16, height: 16 }} /> : <md-icon slot="icon">refresh</md-icon>}
        Build lại
      </md-filled-tonal-button> : null}
      <OpenButton site={site} variant="filled" label="Mở site" />
    </>}>
    <div className="md-stack" style={{ minWidth: "min(440px, 80vw)", gap: 12 }}>
      <p className="md-card__subtitle" style={{ margin: 0 }}>{site.pages} trang · {site.files} file nguồn</p>
      {site.buildError ? <div className="md-banner md-banner--error">
        <md-icon>error</md-icon>
        <div className="md-banner__text"><strong>Build lỗi.</strong> <code>{site.buildError}</code></div>
      </div> : null}
      <div className="md-row" style={{ alignItems: "center", gap: 8 }}>
        <Badge icon="schedule">Build: {site.builtAt || "chưa"}</Badge>
        {site.readonly ? <Badge tone="primary" icon="inventory_2">Data pack · {site.pack}</Badge> : null}
      </div>
      {site.src ? <p className="md-card__subtitle" style={{ margin: 0, wordBreak: "break-all" }}>
        Nguồn: <code>{site.src}</code>
      </p> : null}
    </div>
  </Dialog>;
}
