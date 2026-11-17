// Create a docs site (or replace a site's sources) from a folder, kept with its relative paths, or one .zip.
import React, { useRef, useState } from "react";
import { Dialog, TextField } from "../../md/react.jsx";
import { uploadWithProgress } from "../../app/http.js";

const ALLOWED = /\.(md|markdown|png|jpe?g|gif|svg|webp|pdf|css|ya?ml|txt|csv|json|zip)$/i;
const pathOf = (file) => file.relativePath || file.webkitRelativePath || file.name;

// Dropped folders: walk the entries so subfolders keep their paths.
async function walk(entry, prefix = "") {
  if (entry.isFile) {
    const file = await new Promise((resolve, reject) => entry.file(resolve, reject));
    file.relativePath = prefix + file.name;
    return [file];
  }
  const reader = entry.createReader();
  const all = [];
  for (;;) {
    const batch = await new Promise((resolve, reject) => reader.readEntries(resolve, reject));
    if (!batch.length) break;
    for (const child of batch) all.push(...(await walk(child, `${prefix}${entry.name}/`)));
  }
  return all;
}

export default function UploadDialog({ site, onClose, onDone }) {
  const [title, setTitle] = useState(site?.title || "");
  const [files, setFiles] = useState([]);
  const [label, setLabel] = useState("Kéo thả thư mục vào đây");
  const [progress, setProgress] = useState(null);
  const [active, setActive] = useState(false);
  const folder = useRef(null);
  const zip = useRef(null);

  const isBusy = progress !== null;
  const isBuilding = progress !== null && progress >= 1;

  const choose = (list, name) => {
    const kept = list.filter((file) => ALLOWED.test(file.name) && !/(^|\/)\./.test(pathOf(file)));
    setFiles(kept);
    setLabel(kept.length ? `${name} · ${kept.length} file` : "Không có file markdown phù hợp");
  };
  const submit = async (close) => {
    const form = new FormData();
    form.append("title", title);
    if (site) form.append("site_id", site.id);
    files.forEach((file) => form.append("file", file, pathOf(file)));
    setProgress(0);
    try {
      const result = await uploadWithProgress("/docs/api/sites", form, setProgress);
      window.md?.snackbar(result.message);
      setProgress(null);
      close();
      onDone?.(result);
    } catch (error) {
      window.md?.snackbar(error.message);
      setProgress(null);
    }
  };
  return <Dialog headline={site ? "Cập nhật nguồn markdown" : "Tạo docs site"} onClose={() => { if (!isBusy) onClose?.(); }}
    actions={(close) => <>
      <md-text-button disabled={isBusy || undefined} onClick={close}>Huỷ</md-text-button>
      <md-filled-button disabled={!files.length || isBusy || undefined} onClick={() => submit(close)}>
        {isBusy ? <md-circular-progress indeterminate slot="icon" style={{ width: 16, height: 16 }}></md-circular-progress> : null}
        {isBuilding ? "Đang build..." : isBusy ? "Đang tải..." : site ? "Cập nhật" : "Tạo"}
      </md-filled-button>
    </>}>
    <div className="md-stack" style={{ minWidth: "min(440px, 80vw)" }}>
      <TextField label="Tên site" value={title} onChange={setTitle} readOnly={isBusy || undefined} supportingText="Để trống thì lấy tên thư mục" />
      <div className={`md-dropzone${active ? " md-dropzone--active" : ""}`}
        onDragEnter={(e) => { e.preventDefault(); if (!isBusy) setActive(true); }}
        onDragOver={(e) => { e.preventDefault(); if (!isBusy) setActive(true); }}
        onDragLeave={(e) => { e.preventDefault(); setActive(false); }}
        onDrop={async (e) => {
          e.preventDefault();
          setActive(false);
          if (isBusy) return;
          const entries = [...e.dataTransfer.items].map((item) => item.webkitGetAsEntry?.()).filter(Boolean);
          choose((await Promise.all(entries.map((entry) => walk(entry)))).flat(), entries[0]?.name || "Thư mục");
        }}>
        <md-icon>drive_folder_upload</md-icon>
        <span className="md-title-small">{label}</span>
        <div className="md-row" style={{ justifyContent: "center" }}>
          <md-outlined-button disabled={isBusy || undefined} onClick={() => folder.current?.click()}><md-icon slot="icon">folder</md-icon>Chọn thư mục</md-outlined-button>
          <md-outlined-button disabled={isBusy || undefined} onClick={() => zip.current?.click()}><md-icon slot="icon">folder_zip</md-icon>Chọn .zip</md-outlined-button>
        </div>
        <input ref={folder} type="file" webkitdirectory="" multiple hidden onChange={(e) => {
          const list = [...e.target.files];
          choose(list, list[0]?.webkitRelativePath.split("/")[0] || "Thư mục");
        }} />
        <input ref={zip} type="file" accept=".zip,application/zip" hidden onChange={(e) => choose([...e.target.files], e.target.files[0]?.name || ".zip")} />
      </div>
      {isBusy ? <div className="md-stack" style={{ gap: 6 }}>
        <div className="md-row" style={{ alignItems: "center", gap: 8 }}>
          <md-circular-progress indeterminate style={{ width: 14, height: 14 }}></md-circular-progress>
          <span className="md-body-small">
            {isBuilding ? "Đang build site markdown..." : `Đang tải lên (${Math.round(progress * 100)}%)...`}
          </span>
        </div>
        {isBuilding ? (
          <md-linear-progress indeterminate style={{ width: "100%" }}></md-linear-progress>
        ) : (
          <md-linear-progress value={progress} style={{ width: "100%" }}></md-linear-progress>
        )}
      </div> : null}
    </div>
  </Dialog>;
}
