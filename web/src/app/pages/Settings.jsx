// Settings: data folder, data packs (import .sapack, switch version), addons (install .zip, remove), backups.
import React, { useRef, useState } from "react";
import { Checkbox, Dialog } from "../../md/react.jsx";
import { useApp, useTitle } from "../context.jsx";
import { http } from "../http.js";
import { Badge, ListItem, PageHeader, useAction, useLoad } from "../ui.jsx";

const TRUST = { signed: ["success", "verified", "Đã ký"], unsigned: [null, "person", "Chưa ký"], modified: ["error", "warning", "Đã bị sửa"] };
const DEPS = { broken: ["error", "link_off", "Thiếu phụ thuộc"], degraded: ["warning", "link", "Thiếu phụ thuộc tuỳ chọn"] };
const LEVEL = { block: ["error", "Chặn"], warn: ["warning", "Cần đồng ý"], note: ["info", "Lưu ý"] };

/** What one addon reads of others and who reads it (addon.json uses / exports), one line for the list. */
function relations(addon) {
  const uses = addon.deps?.uses || [];
  const usedBy = addon.deps?.usedBy || [];
  const parts = [];
  if (uses.length) parts.push(`dùng dữ liệu của ${uses.map((u) => u.name).join(", ")}`);
  if (usedBy.length) parts.push(`được dùng bởi ${usedBy.map((u) => u.name).join(", ")}`);
  return parts.length ? ` · ${parts.join(" · ")}` : "";
}

// The compatibility report of an install or a removal (viewer_hub/addons/deps.py): a block stops it; each warning
// must be ticked before "Vẫn tiếp tục"; notes only inform.
function ReviewDialog({ review, verb, onAccept, onClose }) {
  const warnings = review.issues.filter((i) => i.level === "warn");
  const [ticked, setTicked] = useState(() => new Set());
  const all = warnings.every((i) => ticked.has(i.key));
  const tick = (key, on) => setTicked((current) => {
    const next = new Set(current);
    if (on) next.add(key); else next.delete(key);
    return next;
  });
  return <Dialog icon={review.blocked ? "block" : "rule"} className={review.blocked ? "md-dialog--danger" : ""} wide
    headline={`${review.blocked ? "Không thể" : "Kiểm tra trước khi"} ${verb} ${review.addon.name} ${review.addon.version}`}
    onClose={onClose}
    actions={(close) => <>
      <md-text-button onClick={close}>{review.blocked ? "Đóng" : "Huỷ"}</md-text-button>
      {review.blocked ? null : <md-filled-button disabled={!all || undefined} onClick={() => { close(); onAccept(warnings.map((i) => i.key)); }}>
        Vẫn {verb}</md-filled-button>}
    </>}>
    <p>{review.blocked
      ? "Addon này không tương thích với các addon đã cài. Báo admin / tác giả addon theo các mục dưới đây."
      : "Một số addon đang dùng dữ liệu của nhau. Đọc từng mục; tick để xác nhận bạn hiểu ảnh hưởng."}</p>
    <ul className="md-list">
      {review.issues.map((issue) => {
        const [tone, label] = LEVEL[issue.level] || LEVEL.note;
        return <li key={issue.key || issue.message} className="md-list-item">
          {issue.level === "warn"
            ? <Checkbox checked={ticked.has(issue.key)} onChange={(on) => tick(issue.key, on)} label={issue.message} />
            : <div className="md-row"><Badge tone={tone}>{label}</Badge><span>{issue.message}</span></div>}
        </li>;
      })}
    </ul>
  </Dialog>;
}

// Addons: features installed as a zip into the data folder (viewer_hub/addons), no new Viewer Hub version needed.
// A locked premium addon is only counted, never named.
function Addons({ readonly }) {
  const { reload: reloadApp } = useApp();
  const { data, reload } = useLoad(() => http.get("/api/addons"));
  const [run, busy] = useAction();
  const [removing, setRemoving] = useState(null);
  const [notes, setNotes] = useState(null);
  const [review, setReview] = useState(null); // {review, verb, retry(accept)}
  const file = useRef(null);
  const changed = () => { reload(); reloadApp(); };
  // An install or removal the Hub sent back for review (409 needs_review): show the report, retry with the accepted keys.
  const attempt = async (action, verb, retry) => {
    try {
      return await run(async () => {
        try {
          return await action();
        } catch (error) {
          if (error.status === 409 && error.body?.review) {
            setReview({ review: error.body.review, verb, retry });
            return undefined;
          }
          throw error;
        }
      }, (r) => r?.message);
    } catch {
      return undefined;
    }
  };
  const installed = (result) => {
    if (!result) return;
    if (result.notes?.length) setNotes(result.notes);
    changed();
  };
  const pick = async (event) => {
    const chosen = event.target.files?.[0];
    event.target.value = "";
    if (!chosen) return;
    const form = new FormData();
    form.append("file", chosen);
    // the second request installs the zip the Hub kept (its token), checked again with the accepted warnings
    const retry = async (accept, report) => installed(await attempt(
      () => http.post(`/api/addons/staged/${encodeURIComponent(report.token)}`, { accept }), "cài", retry));
    installed(await attempt(() => http.upload("/api/addons", form), "cài", retry));
  };
  const remove = async (target, accept) => {
    const result = await attempt(() => http.delete(`/api/addons/${encodeURIComponent(target.id)}`, accept ? { accept } : undefined),
      "gỡ", (keys) => remove(target, keys));
    if (result) changed();
  };
  return <section className="md-card md-card--outlined">
    <div className="md-card__body">
      <div className="md-row">
        <h2 className="md-card__title md-spacer">Addon</h2>
        <md-text-button href="/api/addons/sdk" title="Bộ viết addon: AGENTS.md cho AI, mẫu addon, công cụ build trang">
          <md-icon slot="icon">download</md-icon>Tải SDK</md-text-button>
        <input ref={file} type="file" accept=".zip" hidden onChange={pick} />
        <md-filled-tonal-button disabled={readonly || busy || undefined} onClick={() => file.current?.click()}>
          <md-icon slot="icon">extension</md-icon>Cài addon (.zip)</md-filled-tonal-button>
      </div>
      <p className="md-card__subtitle">Tính năng thêm do admin gửi, cài vào thư mục dữ liệu, không cần bản Viewer Hub mới. Chỉ cài addon từ admin: addon chạy với quyền của bạn trên máy này. Gỡ addon vẫn giữ dữ liệu của nó. Tự viết addon: <strong>Tải SDK</strong>, mở bằng công cụ AI (đọc AGENTS.md), đóng zip rồi cài ở đây.</p>
      {data?.locked ? <p className="md-card__subtitle"><md-icon style={{ "--md-icon-size": "16px" }}>lock</md-icon> {data.locked} addon cần mã mở khoá (mục Premium).</p> : null}
    </div>
    {data?.addons.length ? <ul className="md-list">
      {data.addons.map((addon) => {
        const [tone, icon, trust] = TRUST[addon.trust] || TRUST.unsigned;
        return <ListItem key={addon.id} icon={addon.icon} headline={addon.label}
          supporting={`${addon.name} · ${addon.version} · ${{ daemon: "dịch vụ", external: "chương trình ngoài" }[addon.lifecycle] || "chạy khi cần"}${relations(addon)}`}>
          {DEPS[addon.deps?.state] ? <span title={addon.deps.reasons.join("\n")}>
            <Badge tone={DEPS[addon.deps.state][0]} icon={DEPS[addon.deps.state][1]}>{DEPS[addon.deps.state][2]}</Badge></span> : null}
          <Badge tone={tone} icon={icon}>{trust}</Badge>
          {addon.running ? <Badge tone="success" icon="check_circle">{addon.lifecycle === "external" ? "Đã kết nối" : "Đang chạy"}</Badge> : null}
          <md-icon-button class="md-button--danger" aria-label={`Gỡ ${addon.label}`} title="Gỡ addon" disabled={readonly || busy || undefined}
            onClick={() => setRemoving(addon)}><md-icon>delete</md-icon></md-icon-button>
        </ListItem>;
      })}
    </ul> : null}
    {data?.broken.length ? <ul className="md-list">
      {data.broken.map((item) => <ListItem key={item.folder} icon="error" headline={`addons/${item.folder}`} supporting={item.error} />)}
    </ul> : null}
    {data?.held?.length ? <ul className="md-list">
      {data.held.map((item) => <ListItem key={item.id} icon="pause_circle" headline={`Chưa cập nhật bản mặc định của ${item.id}`}
        supporting={`${item.message}. Cập nhật các addon đang dùng nó trước, hoặc tự cài file zip để xem và đồng ý.`} />)}
    </ul> : null}
    {review ? <ReviewDialog review={review.review} verb={review.verb} onClose={() => setReview(null)}
      onAccept={(keys) => review.retry?.(keys, review.review)} /> : null}
    {removing ? <Dialog icon="delete" className="md-dialog--danger" headline={`Gỡ ${removing.label}?`} onClose={() => setRemoving(null)}
      actions={(close) => <>
        <md-text-button onClick={close}>Huỷ</md-text-button>
        <md-filled-button class="md-button--danger" onClick={async () => {
          const target = removing;
          close();
          await remove(target);
        }}>Gỡ</md-filled-button>
      </>}><p>Addon dừng và biến khỏi menu. Dữ liệu và cài đặt của nó vẫn giữ: cài lại là dùng tiếp.</p></Dialog> : null}
    {notes ? <Dialog icon="info" headline="Lưu ý về addon vừa cài" onClose={() => setNotes(null)}
      actions={(close) => <md-text-button onClick={close}>Đã hiểu</md-text-button>}>
      <p>Addon này làm những việc Viewer Hub không tự làm. Chỉ dùng nếu admin đã kiểm tra:</p>
      <ul>{notes.map((note) => <li key={note}><code>{note}</code></li>)}</ul>
    </Dialog> : null}
  </section>;
}

export default function Settings() {
  useTitle("Cài đặt");
  const { app } = useApp();
  const { data, reload } = useLoad(() => http.get("/api/settings"));
  const [run, busy] = useAction();
  const file = useRef(null);
  const readonly = app.readonly;
  const pick = async (event) => {
    const chosen = event.target.files?.[0];
    event.target.value = "";
    if (!chosen) return;
    const form = new FormData();
    form.append("file", chosen);
    const result = await run(() => http.upload("/api/settings/import", form), (r) => r.message);
    if (result) reload();
  };
  if (!data) return <PageHeader subtitle="Thư mục dữ liệu, data pack, addon và sao lưu." />;
  return <>
    <PageHeader subtitle="Thư mục dữ liệu, data pack, addon và sao lưu." />
    <div className="md-stack">
      <section className="md-card md-card--outlined">
        <div className="md-card__body">
          <h2 className="md-card__title">Thư mục dữ liệu</h2>
          <p className="md-card__subtitle">Dữ liệu của bạn nằm ngoài thư mục chương trình, nên cập nhật phiên bản mới không làm mất dữ liệu.</p>
          <pre className="md-code">{data.home}</pre>
          <div className="md-row">
            <Badge>Phiên bản {app.version}</Badge>
            <Badge>Schema {data.schema}</Badge>
            {readonly ? <Badge tone="error" icon="lock">Chỉ đọc</Badge> : null}
          </div>
        </div>
      </section>

      <section className="md-card md-card--outlined">
        <div className="md-card__body">
          <div className="md-row">
            <h2 className="md-card__title md-spacer">Data pack</h2>
            <input ref={file} type="file" accept=".sapack" hidden onChange={pick} />
            <md-filled-tonal-button disabled={readonly || busy || undefined} onClick={() => file.current?.click()}>
              <md-icon slot="icon">upload</md-icon>Import .sapack</md-filled-tonal-button>
          </div>
          <p className="md-card__subtitle">Dữ liệu admin gửi (F-Search, code map). Import chỉ thêm phiên bản mới, không động tới CSV, Docs hay ghi chú của bạn; bản cũ được giữ để quay lại bằng “Dùng bản này”. Pack cũ hơn bản đang dùng được nạp nhưng không tự bật.</p>
        </div>
        {data.packs.length ? <ul className="md-list">
          {data.packs.map((pack) => <ListItem key={`${pack.id}@${pack.version}`} icon="inventory_2" headline={pack.title}
            supporting={`${pack.id} · ${pack.version} · ${(pack.imported_at || "").slice(0, 10)}`}>
            {pack.active ? <Badge tone="primary">Đang dùng</Badge>
              : <md-text-button disabled={readonly || busy || undefined} onClick={async () => {
                if (await run(() => http.post("/api/settings/packs/activate", { id: pack.id, version: pack.version }), (r) => r.message)) reload();
              }}><md-icon slot="icon">history</md-icon>Dùng bản này</md-text-button>}
          </ListItem>)}
        </ul> : null}
      </section>

      <Addons readonly={readonly} />

      <section className="md-card md-card--outlined">
        <div className="md-card__body">
          <div className="md-row">
            <h2 className="md-card__title md-spacer">Sao lưu</h2>
            <md-filled-tonal-button disabled={busy || undefined} onClick={async () => {
              if (await run(() => http.post("/api/settings/backup"), (r) => r.message)) reload();
            }}><md-icon slot="icon">backup</md-icon>Sao lưu ngay</md-filled-tonal-button>
          </div>
          <p className="md-card__subtitle">Tự động sao lưu trước mỗi lần nâng cấp dữ liệu; giữ 5 bản gần nhất. Khôi phục: <code>viewer-hub restore &lt;thư mục&gt;</code>.</p>
        </div>
        {data.backups.length ? <ul className="md-list">
          {data.backups.map((item) => <ListItem key={item.name} icon="history" headline={item.name} supporting={item.path} />)}
        </ul> : null}
      </section>
    </div>
  </>;
}
