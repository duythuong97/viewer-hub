// Describe one or more datasets (after an upload) or edit one; saves each with PATCH.
import React, { useState } from "react";
import { Dialog } from "../../md/react.jsx";
import { http } from "../../app/http.js";
import { useAction } from "../../app/ui.jsx";
import InfoFields, { infoOf } from "./InfoFields.jsx";
import { API } from "./index.jsx";

export default function InfoDialog({ datasets, headline, icon, cancel = "Huỷ", onClose, onSaved }) {
  const [values, setValues] = useState(() => Object.fromEntries(datasets.map((d) => [d.id, infoOf(d)])));
  const [run, busy] = useAction();
  const save = async (close) => {
    const done = await run(async () => {
      for (const d of datasets) await http.patch(`${API}/${encodeURIComponent(d.id)}`, values[d.id]);
      return true;
    }, datasets.length === 1 ? `Đã lưu thông tin ${values[datasets[0].id].title || datasets[0].title}` : `Đã lưu thông tin ${datasets.length} file`);
    if (done) { close(); onSaved?.(); }
  };
  return <Dialog headline={headline} icon={icon} className="csv-info-dialog" onClose={onClose}
    actions={(close) => <>
      <md-text-button onClick={close}>{cancel}</md-text-button>
      <md-filled-button disabled={busy || undefined} onClick={() => save(close)}><md-icon slot="icon">save</md-icon>Lưu</md-filled-button>
    </>}>
    <div className="md-stack">
      {datasets.map((d) => <InfoFields key={d.id} dataset={d} value={values[d.id]}
        onChange={(next) => setValues({ ...values, [d.id]: next })} />)}
    </div>
  </Dialog>;
}
