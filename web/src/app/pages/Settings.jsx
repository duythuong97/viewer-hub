// Settings: data folder, data packs (import .sapack, switch version), addons (install .zip, remove), backups.
import React, { useRef, useState } from "react";
import { Button, Checkbox, Dialog, IconButton, Switch, TextField } from "../../md/react.jsx";
import { useApp, useTitle } from "../context.jsx";
import { http, uploadWithProgress } from "../http.js";
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

function parseAddonNotes(notes = []) {
  const definitions = {
    "chạy tiến trình": {
      label: "Chạy tiến trình / Mở ứng dụng ngoài",
      icon: "terminal",
      desc: "Addon khởi chạy lệnh hoặc mở tệp bằng ứng dụng mặc định trên hệ điều hành.",
    },
    "chạy tiến trình (child_process)": {
      label: "Chạy tiến trình nền (child_process)",
      icon: "terminal",
      desc: "Addon khởi chạy tiến trình con để xử lý tác vụ nền.",
    },
    "gọi mạng": {
      label: "Kết nối mạng (Network requests)",
      icon: "language",
      desc: "Addon gửi yêu cầu mạng tới dịch vụ nội bộ hoặc máy chủ theo thiết kế.",
    },
    "payload base64": {
      label: "Xử lý dữ liệu nhúng (Base64)",
      icon: "data_object",
      desc: "Addon giải mã hoặc kết xuất tài nguyên nhúng (hình ảnh đồ họa, sơ đồ, tệp nén).",
    },
    "socket / named pipe": {
      label: "Kênh liên lạc nội bộ (IPC Socket / Pipe)",
      icon: "settings_input_component",
      desc: "Addon kết nối qua socket nội bộ giữa các tiến trình trên máy.",
    },
    "nhắc tới PowerShell / cmd": {
      label: "Lệnh dòng lệnh hệ điều hành (CLI Scripts)",
      icon: "code",
      desc: "Addon có chứa câu lệnh hoặc công cụ dòng lệnh hệ thống.",
    },
    "eval trong JS": {
      label: "Tính toán biểu thức động",
      icon: "calculate",
      desc: "Addon sử dụng cơ chế đánh giá biểu thức động.",
    },
  };

  const groups = new Map();
  const rawList = [];

  for (const item of notes) {
    rawList.push(item);
    let matchedDef = null;
    let matchedKey = "";
    for (const [key, def] of Object.entries(definitions)) {
      if (item.includes(key)) {
        matchedDef = def;
        matchedKey = key;
        break;
      }
    }

    if (matchedDef) {
      if (!groups.has(matchedKey)) {
        groups.set(matchedKey, { ...matchedDef, count: 0, items: [] });
      }
      const g = groups.get(matchedKey);
      g.count += 1;
      g.items.push(item);
    } else {
      const otherKey = item.includes("GUIDE.md") ? "guide" : "other";
      if (!groups.has(otherKey)) {
        groups.set(otherKey, {
          label: otherKey === "guide" ? "Tài liệu hướng dẫn (GUIDE.md)" : "Lưu ý khác",
          icon: otherKey === "guide" ? "menu_book" : "info",
          desc: item,
          count: 0,
          items: [],
        });
      }
      const g = groups.get(otherKey);
      g.count += 1;
      g.items.push(item);
    }
  }

  return { groups: Array.from(groups.values()), rawList };
}

function AddonNotesDialog({ notes, onClose }) {
  const { groups, rawList } = parseAddonNotes(notes);

  return (
    <Dialog
      icon="verified_user"
      headline="Thông tin quyền hạn của Addon vừa cài"
      onClose={onClose}
      wide
      actions={(close) => (
        <md-filled-button onClick={close}>Đã hiểu & Đóng</md-filled-button>
      )}
    >
      <p className="md-body-medium" style={{ margin: "0 0 14px", lineHeight: 1.5 }}>
        Addon đã được cài đặt thành công và sẵn sàng hoạt động. Dưới đây là tóm tắt các quyền và tác vụ hệ thống mà addon này sử dụng:
      </p>

      <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
        {groups.map((group, idx) => (
          <div
            key={idx}
            style={{
              padding: "10px 14px",
              borderRadius: 8,
              border: "1px solid var(--md-sys-color-outline-variant)",
              background: "var(--md-sys-color-surface-container-low)",
              display: "flex",
              gap: 12,
              alignItems: "flex-start",
            }}
          >
            <md-icon style={{ color: "var(--md-sys-color-primary)", fontSize: 22, marginTop: 2 }}>
              {group.icon}
            </md-icon>
            <div style={{ flex: 1 }}>
              <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
                <strong style={{ fontSize: 13, color: "var(--md-sys-color-on-surface)" }}>
                  {group.label}
                </strong>
                {group.count > 1 ? (
                  <span className="md-badge" style={{ fontSize: 11, height: 18 }}>
                    {group.count} vị trí
                  </span>
                ) : null}
              </div>
              <p style={{ margin: "4px 0 0", fontSize: 12, color: "var(--md-sys-color-on-surface-variant)", lineHeight: 1.4 }}>
                {group.desc}
              </p>
            </div>
          </div>
        ))}
      </div>

      <details style={{ marginTop: 14, fontSize: 12 }}>
        <summary style={{ cursor: "pointer", color: "var(--md-sys-color-primary)", fontWeight: 500, padding: "4px 0" }}>
          Chi tiết mã nguồn quét được (dành cho Admin / Nhà phát triển)
        </summary>
        <div
          style={{
            marginTop: 8,
            padding: "8px 12px",
            borderRadius: 6,
            background: "var(--md-sys-color-surface-container)",
            maxHeight: 140,
            overflowY: "auto",
            fontFamily: "var(--md-ref-typeface-mono)",
            fontSize: 11,
          }}
        >
          {rawList.map((note, i) => (
            <div key={i} style={{ padding: "2px 0", color: "var(--md-sys-color-on-surface-variant)" }}>
              {note}
            </div>
          ))}
        </div>
      </details>
    </Dialog>
  );
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
  // Switched off: kept installed with its data, but gone from the menu, the guide and MCP until switched on again.
  const toggle = async (target, on) => {
    const result = await attempt(() => http.post(`/api/addons/${encodeURIComponent(target.id)}/enable`, { on }), on ? "bật" : "tắt");
    if (result) changed(); else reload();
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
      <p className="md-card__subtitle">Tính năng thêm do admin gửi, cài vào thư mục dữ liệu, không cần bản Viewer Hub mới. Chỉ cài addon từ admin: addon chạy với quyền của bạn trên máy này. Tắt addon bằng công tắc để ẩn tạm (dữ liệu giữ nguyên); gỡ addon vẫn giữ dữ liệu của nó. Tự viết addon: <strong>Tải SDK</strong>, mở bằng công cụ AI (đọc AGENTS.md), đóng zip rồi cài ở đây.</p>
      {data?.locked ? <p className="md-card__subtitle"><md-icon style={{ "--md-icon-size": "16px" }}>lock</md-icon> {data.locked} addon cần mã mở khoá (mục Premium).</p> : null}
    </div>
    {data?.addons.length ? <ul className="md-list">
      {data.addons.map((addon) => {
        const [tone, icon, trust] = TRUST[addon.trust] || TRUST.unsigned;
        return <ListItem key={addon.id} icon={addon.enabled ? addon.icon : "extension_off"} headline={addon.label}
          supporting={`${addon.name} · ${addon.version} · ${{ daemon: "dịch vụ", external: "chương trình ngoài" }[addon.lifecycle] || "chạy khi cần"}${relations(addon)}`}>
          {DEPS[addon.deps?.state] ? <span title={addon.deps.reasons.join("\n")}>
            <Badge tone={DEPS[addon.deps.state][0]} icon={DEPS[addon.deps.state][1]}>{DEPS[addon.deps.state][2]}</Badge></span> : null}
          <Badge tone={tone} icon={icon}>{trust}</Badge>
          {!addon.enabled ? <Badge icon="block">Đã tắt</Badge> : addon.running
            ? <Badge tone="success" icon="check_circle">{addon.lifecycle === "external" ? "Đã kết nối" : "Đang chạy"}</Badge> : null}
          <Switch selected={addon.enabled} disabled={readonly || busy} label={`Bật ${addon.label}`}
            title={addon.enabled ? "Tắt addon: ẩn khỏi menu, hướng dẫn và MCP, dừng tiến trình; dữ liệu vẫn giữ" : "Bật lại addon"}
            onChange={(on) => toggle(addon, on)} />
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
    {notes ? <AddonNotesDialog notes={notes} onClose={() => setNotes(null)} /> : null}
  </section>;
}

function syncLine(last) {
  if (!last) return "Chưa đồng bộ";
  const at = (last.at || "").replace("T", " ");
  if (last.error) return `Lỗi lúc ${at}: ${last.error}`;
  const changes = [last.written?.length ? `cập nhật ${last.written.length}` : "", last.removed?.length ? `xoá ${last.removed.length}` : ""]
    .filter(Boolean).join(", ");
  return `${last.skills} skill · đồng bộ lúc ${at}${changes ? ` (${changes})` : " (không đổi)"}`;
}

// GitHub Copilot: the mcp.json block (address taken now, so the current port), the skills zip, and the project folders
// that get the skills in .github/skills on every start (viewer_hub/app/copilot_sync.py).
function CopilotSetup({ readonly }) {
  const { data, reload } = useLoad(() => http.get("/api/settings/copilot"));
  const [adding, setAdding] = useState("");
  const [saving, setSaving] = useState(false);
  const folders = data?.folders || [];
  const copy = async () => {
    try {
      const config = await http.get("/api/mcp/config");
      await navigator.clipboard.writeText(JSON.stringify(config, null, 2));
      window.md?.snackbar("Đã sao chép cấu hình MCP. Dán vào .vscode/mcp.json");
    } catch (error) {
      window.md?.snackbar(error.message || "Không sao chép được");
    }
  };
  const save = async (paths, message) => {
    setSaving(true);
    try {
      const result = await http.put("/api/settings/copilot", { folders: paths });
      const failed = result.folders.filter((folder) => folder.last?.error);
      window.md?.snackbar(failed.length ? `${message}. ${failed.length} folder lỗi, xem bên dưới` : message);
      setAdding("");
      reload();
    } catch (error) {
      window.md?.snackbar(error.message || "Không lưu được");
    } finally {
      setSaving(false);
    }
  };
  const add = () => adding.trim() && save([...folders.map((folder) => folder.path), adding.trim()], "Đã thêm folder và đồng bộ skills");
  return <section className="md-card md-card--outlined">
    <div className="md-card__body">
      <h2 className="md-card__title">Dùng với GitHub Copilot</h2>
      <p className="md-card__subtitle">Sao chép cấu hình MCP (dán vào <code>.vscode/mcp.json</code>), tải skills (giải nén vào
        <code> .github/skills/</code> của folder). Đổi cổng thì sao chép lại.</p>
      <div className="md-row">
        <Button variant="filled" icon="content_copy" onClick={copy}>Sao chép cấu hình MCP</Button>
        <Button variant="tonal" icon="download" onClick={() => { window.location.href = "/api/mcp/skills.zip"; }}>Tải skills (.zip)</Button>
      </div>
      <h3 className="md-card__title" style={{ marginTop: 16 }}>Tự đồng bộ skills vào folder</h3>
      <p className="md-card__subtitle">Mỗi lần Viewer Hub khởi động (và khi lưu danh sách), skills được ghi vào
        <code> .github/skills/</code> của từng folder dưới đây: thêm skill mới, cập nhật skill đã đổi, xoá skill không còn
        dùng. Chỉ đụng tới skill do Viewer Hub tạo; skill bạn tự viết giữ nguyên.</p>
    </div>
    {folders.length ? <ul className="md-list">
      {folders.map((folder) => <ListItem key={folder.path} icon={folder.last?.error ? "folder_off" : "folder"} headline={folder.path}
        supporting={syncLine(folder.last)}>
        <IconButton icon="delete" label="Bỏ folder này" disabled={readonly || saving}
          onClick={() => save(folders.filter((other) => other.path !== folder.path).map((other) => other.path), "Đã bỏ folder")} />
      </ListItem>)}
    </ul> : null}
    <div className="md-card__body">
      <div className="md-row">
        <TextField className="md-spacer" label="Đường dẫn folder" placeholder="C:\work\order-system hoặc /Users/me/repo"
          value={adding} onChange={setAdding} onKeyDown={(event) => { if (event.key === "Enter") add(); }}
          supportingText={`Đường dẫn đầy đủ tới folder project (repo) mở bằng VS Code. Tối đa ${data?.max || 20} folder.`} />
        <Button variant="tonal" icon="add" disabled={readonly || saving || !adding.trim()} onClick={add}>Thêm</Button>
        {folders.length ? <Button icon="sync" disabled={readonly || saving}
          onClick={() => save(folders.map((folder) => folder.path), "Đã đồng bộ skills")}>Đồng bộ ngay</Button> : null}
      </div>
    </div>
  </section>;
}

export default function Settings() {
  useTitle("Cài đặt");
  const { app } = useApp();
  const { data, reload } = useLoad(() => http.get("/api/settings"));
  const [run, busy] = useAction();
  const file = useRef(null);
  const readonly = app.readonly;
  const [uploadPercent, setUploadPercent] = useState(null);
  const [localPath, setLocalPath] = useState("");
  const [showLocalDialog, setShowLocalDialog] = useState(false);

  const pick = async (event) => {
    const chosen = event.target.files?.[0];
    event.target.value = "";
    if (!chosen) return;
    const form = new FormData();
    form.append("file", chosen);
    setUploadPercent(0);
    try {
      const result = await uploadWithProgress("/api/settings/import", form, (progress) => {
        setUploadPercent(Math.round(progress * 100));
      });
      window.md?.snackbar(result.message || "Đã import thành công");
      reload();
    } catch (err) {
      window.md?.snackbar(`Import thất bại: ${err.message || err}`);
    } finally {
      setUploadPercent(null);
    }
  };

  const handleLocalImport = async () => {
    if (!localPath.trim()) return;
    try {
      const res = await http.post("/api/settings/import", { path: localPath.trim() });
      window.md?.snackbar(res.message || "Đã import thành công");
      setShowLocalDialog(false);
      setLocalPath("");
      reload();
    } catch (err) {
      window.md?.snackbar(`Import thất bại: ${err.message || err}`);
    }
  };

  if (!data) return <PageHeader subtitle="Thư mục dữ liệu, data pack, addon, GitHub Copilot và sao lưu." />;
  return <>
    <PageHeader subtitle="Thư mục dữ liệu, data pack, addon, GitHub Copilot và sao lưu." />
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
            <md-text-button disabled={readonly || busy || uploadPercent !== null || undefined} onClick={() => setShowLocalDialog(true)}>
              <md-icon slot="icon">folder</md-icon>Import từ đường dẫn đĩa</md-text-button>
            <md-filled-tonal-button disabled={readonly || busy || uploadPercent !== null || undefined} onClick={() => file.current?.click()}>
              <md-icon slot="icon">upload</md-icon>Import .sapack</md-filled-tonal-button>
          </div>
          {uploadPercent !== null ? <div style={{ marginTop: 12 }}>
            <md-linear-progress value={uploadPercent / 100} style={{ width: "100%" }}></md-linear-progress>
            <span className="md-muted cm-small">Đang tải lên và xử lý: {uploadPercent}%</span>
          </div> : null}
          <p className="md-card__subtitle">Dữ liệu admin gửi (F-Search, code map). Import chỉ thêm phiên bản mới, không động tới CSV, Docs hay ghi chú của bạn; bản cũ được giữ để quay lại bằng “Dùng bản này”. Pack cũ hơn bản đang dùng được nạp nhưng không tự bật.</p>
        </div>
        {showLocalDialog ? <Dialog headline="Import .sapack từ đường dẫn đĩa" icon="folder" onClose={() => setShowLocalDialog(false)}
          actions={(close) => <>
            <md-text-button onClick={close}>Huỷ</md-text-button>
            <md-filled-button disabled={!localPath.trim() || undefined} onClick={handleLocalImport}>Import</md-filled-button>
          </>}>
          <p>Nhập đường dẫn tuyệt đối tới file .sapack trên máy của bạn (khuyên dùng cho file lớn ~3GB để import ngay tức thì mà không cần tải qua mạng trình duyệt):</p>
          <TextField label="Đường dẫn file .sapack" placeholder="/path/to/file.sapack hoặc C:\path\file.sapack" value={localPath} onChange={setLocalPath} />
        </Dialog> : null}
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

      <CopilotSetup readonly={readonly} />

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
