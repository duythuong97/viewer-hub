// The datasets: upload (drop or pick, several at once), then describe; cards with Sửa / Mở.
import React, { useRef, useState } from "react";
import { useApp, useTitle } from "../../app/context.jsx";
import { uploadWithProgress } from "../../app/http.js";
import { useRouter } from "../../app/router.jsx";
import { Badge, PageHeader } from "../../app/ui.jsx";
import InfoDialog from "./InfoDialog.jsx";
import { API } from "./index.jsx";

/** Upload CSV files; returns the created datasets (errors and skipped files go to the snackbar). */
export async function uploadCsv(files, onProgress) {
  const form = new FormData();
  [...files].forEach((file) => form.append("file", file, file.name));
  try {
    const result = await uploadWithProgress(API, form, onProgress);
    window.md?.snackbar([result.message, ...result.skipped].join(" · "));
    return result.created;
  } catch (error) {
    window.md?.snackbar(error.message);
    return [];
  }
}

export default function ListPage({ datasets, reload }) {
  useTitle("CSV");
  const { app } = useApp();
  const { navigate } = useRouter();
  const input = useRef(null);
  const [busy, setBusy] = useState(false);
  const [active, setActive] = useState(false);
  const [describe, setDescribe] = useState(null);
  const [editing, setEditing] = useState(null);

  const upload = async (files) => {
    if (!files.length || app.readonly) return;
    setBusy(true);
    const created = await uploadCsv(files);
    setBusy(false);
    if (created.length) { setDescribe(created); reload(); }
  };
  return <>
    <PageHeader subtitle="Tải file CSV lên: tiêu đề cột, encoding và dấu phân cách được nhận tự động." />
    <div className={`md-dropzone${active ? " md-dropzone--active" : ""}`}
      onDragEnter={(e) => { e.preventDefault(); setActive(true); }} onDragOver={(e) => { e.preventDefault(); setActive(true); }}
      onDragLeave={(e) => { e.preventDefault(); setActive(false); }}
      onDrop={(e) => { e.preventDefault(); setActive(false); upload(e.dataTransfer.files); }}>
      <md-icon>upload_file</md-icon>
      <span className="md-title-medium">Kéo thả file CSV vào đây</span>
      <span className="md-body-medium">hoặc chọn file · UTF-8, UTF-8 BOM, Shift_JIS, … · dấu , ; tab |</span>
      <md-filled-tonal-button disabled={app.readonly || busy || undefined} onClick={() => input.current?.click()}>
        <md-icon slot="icon">folder_open</md-icon>Chọn file</md-filled-tonal-button>
      <input ref={input} type="file" accept=".csv,.tsv,.txt,text/csv" multiple hidden
        onChange={(e) => { upload(e.target.files); e.target.value = ""; }} />
    </div>
    {busy ? <md-linear-progress indeterminate style={{ marginTop: 8, width: "100%" }}></md-linear-progress> : null}

    <h2 className="md-section-title">Đã có</h2>
    {datasets.length ? <div className="md-grid">
      {datasets.map((d) => <article key={d.id} className="md-card md-card--outlined">
        <div className="md-card__body">
          <span className="md-card__icon"><md-icon>table_view</md-icon></span>
          <h3 className="md-card__title">{d.title}</h3>
          <p className="md-card__subtitle">{d.rows.toLocaleString()} dòng · {d.columns} cột</p>
          {d.description ? <p className="md-card__subtitle csv-card__desc">{d.description}</p>
            : !d.readonly ? <p className="md-card__subtitle csv-card__desc csv-card__desc--missing">Chưa có mô tả</p> : null}
          <div className="md-row">
            {d.file ? <Badge>{d.file}</Badge> : null}
            {d.readonly ? <Badge tone="primary" icon="inventory_2">Data pack</Badge> : null}
            {d.mcp ? <Badge icon="smart_toy">AI</Badge> : null}
          </div>
        </div>
        <div className="md-card__actions">
          {!d.readonly ? <md-text-button disabled={app.readonly || undefined} onClick={() => setEditing(d)}>
            <md-icon slot="icon">edit</md-icon>Sửa</md-text-button> : null}
          <md-filled-tonal-button onClick={() => navigate(`/csv/${encodeURIComponent(d.id)}`)}>
            <md-icon slot="icon">open_in_new</md-icon>Mở</md-filled-tonal-button>
        </div>
      </article>)}
    </div> : <div className="md-empty"><md-icon>dataset</md-icon><h2>Chưa có bộ dữ liệu</h2><p>Tải một file CSV lên để bắt đầu.</p></div>}

    {describe ? <InfoDialog datasets={describe} headline="Mô tả file vừa tải" icon="edit_note" cancel="Để sau"
      onClose={() => setDescribe(null)}
      onSaved={() => describe.length === 1 ? navigate(`/csv/${encodeURIComponent(describe[0].id)}`) : reload()} /> : null}
    {editing ? <InfoDialog datasets={[editing]} headline={`Sửa “${editing.title}”`} icon="edit"
      onClose={() => setEditing(null)} onSaved={reload} /> : null}
  </>;
}
