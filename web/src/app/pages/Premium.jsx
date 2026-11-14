// Locked features: never named until a code opens them (GUIDELINE §4.5). POST /api/premium/unlock checks the code.
import React, { useState } from "react";
import { Dialog, TextField } from "../../md/react.jsx";
import { useApp, useTitle } from "../context.jsx";
import { http } from "../http.js";
import { useRouter } from "../router.jsx";
import { PageHeader, useAction } from "../ui.jsx";

export default function Premium() {
  useTitle("Premium");
  const { app, reload } = useApp();
  const { navigate } = useRouter();
  const [open, setOpen] = useState(false);
  const [code, setCode] = useState("");
  const [run, busy] = useAction();
  const unlock = async () => {
    const result = await run(() => http.post("/api/premium/unlock", { code }), (r) => r.message);
    if (!result) return;
    await reload();
    navigate(result.path);
  };
  return <>
    <PageHeader subtitle="Nhập mã mở khoá để dùng các tính năng premium." />
    <div className="md-card md-card--outlined">
      <div className="md-empty">
        <md-icon filled>workspace_premium</md-icon>
        <h2>Premium feature</h2>
        <p>Tính năng chưa mở cho bạn.</p>
        <md-filled-tonal-button onClick={() => setOpen(true)}><md-icon slot="icon">volunteer_activism</md-icon>Donate to unlock</md-filled-tonal-button>
      </div>
      <div className="md-card__body md-stack">
        <TextField label="Mã mở khoá" type="textarea" rows={3} value={code} onChange={setCode}
          placeholder="VH2-…" supportingText="Dán nguyên mã admin gửi; không phân biệt hoa thường, dấu gạch hay xuống dòng." />
        <div className="md-row">
          <md-filled-button onClick={unlock} disabled={busy || !code.trim() || app.readonly || undefined}>
            <md-icon slot="icon">lock_open</md-icon>Mở khoá
          </md-filled-button>
        </div>
      </div>
    </div>
    {open ? <Dialog headline="Donate to unlock" icon="volunteer_activism" onClose={() => setOpen(false)}
      actions={(close) => <md-text-button onClick={close}>Đóng</md-text-button>}>
      Liên hệ admin để nhận mã mở khoá premium feature, rồi dán mã vào ô ở trang này.
    </Dialog> : null}
  </>;
}
