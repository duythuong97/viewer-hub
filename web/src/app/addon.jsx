// The Hub's control of one addon (GET /api/addons/<id>, viewer_hub/addons/routes.py), always the Hub's: every addon
// page starts with it (AddonFrame), so a broken or careless addon page never takes away run / stop / log. It is one
// page-header row (status, Nhật ký, Cài đặt) plus a banner only when the user must act; the settings form, the
// service controls and the log open in dialogs. An addon page reads the frame with useAddon().
import React, { createContext, useContext, useEffect, useMemo, useRef, useState } from "react";
import { Button, Dialog, IconButton, Select, Switch, TextField } from "../md/react.jsx";
import { addonApi, http } from "./http.js";
import { Badge, PageHeader, Skeleton, useAction, useConfirm, useLoad } from "./ui.jsx";

const TRUST = {
  signed: ["success", "verified", "Đã ký"],
  unsigned: [null, "person", "Addon do admin cung cấp (chưa ký)"],
  modified: ["error", "warning", "File đã bị sửa sau khi cài"],
};

/** A "records" setting: one card per row with the declared fields (a field shows only while the row's other fields have
 *  the values of its showWhen), add / delete a row. A row saved as a plain string (before the addon had fields) is kept
 *  and shown read-only, so it can be deleted but nothing is lost. */
function Records({ setting, value, onChange }) {
  const rows = Array.isArray(value) ? value : [];
  const fields = setting.fields || [];
  const empty = () => Object.fromEntries(fields.map((field) => [field.key, field.type === "select" ? field.options[0] : ""]));
  const edit = (index, key, text) => onChange(rows.map((row, i) => (i === index ? { ...row, [key]: text } : row)));
  const visible = (row, field) => Object.entries(field.showWhen || {}).every(([other, values]) => values.includes(row[other] ?? ""));
  return <div className="md-stack">
    <div className="md-row"><strong className="md-spacer">{setting.label}</strong>
      <Button icon="add" onClick={() => onChange([...rows, empty()])}>Thêm</Button></div>
    {setting.help ? <div className="md-body-small md-muted">{setting.help}</div> : null}
    {!rows.length ? <div className="md-body-small md-muted">Chưa có mục nào.</div> : null}
    {rows.map((row, index) => <div key={index} className="md-card md-card--outlined"><div className="md-card__body md-stack">
      {typeof row === "string" ? <div className="md-row">
        <div className="md-spacer md-body-small md-muted">Dòng cũ (chưa chuyển sang ô): <code>{row}</code></div>
        <IconButton icon="delete" danger label="Xoá dòng này" onClick={() => onChange(rows.filter((_, i) => i !== index))} /></div>
        : <>
          {/* Three equal columns, every field its own height (align start): a field's note never stretches its neighbours;
              "wide" fields take the whole row. */}
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(200px, 1fr))", gap: 16, alignItems: "start" }}>
            {fields.filter((field) => visible(row, field)).map((field) => <div key={field.key} title={field.help || undefined}
              style={field.wide ? { gridColumn: "1 / -1" } : undefined}>
              {field.type === "select"
                ? <Select label={field.label} value={row[field.key] || ""} options={field.options.map((o) => [o, o])}
                  onChange={(text) => edit(index, field.key, text)} />
                : <TextField label={field.label + (field.required ? " *" : "")} value={row[field.key] ?? ""}
                  placeholder={field.placeholder || undefined} onChange={(text) => edit(index, field.key, text)} />}
            </div>)}
          </div>
          <div className="md-row"><span className="md-spacer" />
            <IconButton icon="delete" danger label="Xoá mục này" onClick={() => onChange(rows.filter((_, i) => i !== index))} /></div>
        </>}
    </div></div>)}
  </div>;
}

function SettingField({ setting, value, onChange }) {
  if (setting.type === "records") return <Records setting={setting} value={value} onChange={onChange} />;
  if (setting.type === "switch") {
    return <Switch selected={Boolean(value)} onChange={onChange} label={setting.label}>{setting.label}</Switch>;
  }
  if (setting.type === "select") {
    return <Select label={setting.label} value={value || ""} onChange={onChange}
      options={setting.options.map((option) => [option, option])} />;
  }
  if (setting.type === "list") {
    return <TextField label={setting.label} type="textarea" rows={4} value={(value || []).join("\n")}
      supportingText={setting.help || "Mỗi dòng một mục"} onChange={(text) => onChange(text.split("\n"))} />;
  }
  return <TextField label={setting.label} value={value ?? ""} onChange={onChange}
    supportingText={setting.help || (setting.type === "folder" ? "Đường dẫn thư mục trên máy" : undefined)}
    leadingIcon={setting.type === "folder" ? "folder" : undefined} />;
}

const POLL_MS = 10000;
export const FrameContext = createContext(null);

/** The whole log of addon `id` (GET /api/addons/<id>/log), newest at the bottom. */
function LogDialog({ id, name, onClose }) {
  const [log, setLog] = useState(null);
  const box = useRef(null);
  const load = () => http.get(`/api/addons/${encodeURIComponent(id)}/log`).then(setLog, (error) => setLog({ text: error.message, file: "" }));
  useEffect(() => { load(); }, [id]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { if (box.current) box.current.scrollTop = box.current.scrollHeight; }, [log]);
  return <Dialog wide icon="receipt_long" headline={`Nhật ký ${name}`} onClose={onClose}
    actions={(close) => <><Button icon="refresh" onClick={load}>Tải lại</Button><Button onClick={close}>Đóng</Button></>}>
    {log === null ? <md-linear-progress indeterminate></md-linear-progress> : <>
      {log.file ? <p className="md-card__subtitle">{log.file}</p> : null}
      <pre ref={box} className="md-code" style={{ maxHeight: "65vh", overflow: "auto", whiteSpace: "pre-wrap", wordBreak: "break-word" }}>
        {log.text || "Chưa có nhật ký."}</pre>
    </>}
  </Dialog>;
}

const filled = (value) => (Array.isArray(value) ? value.some((item) => String(item).trim()) : value !== undefined && value !== null && String(value).trim() !== "");

/** The addon's settings (addon.json "settings") in a dialog; `focus` names the field the caller asked for.
 *  An addon page that exports `setup` ([{ title, Page }]) makes it a guided setup: page 1 is this form (under the optional `setupIntro` component), then one
 *  page per step (Quay lại / Tiếp); each Page gets `{ api, info }` (the addon's api and the panel's info). */
function SettingsDialog({ id, data, focus, setup: guided, onSaved, onClose }) {
  const [values, setValues] = useState(data.values || {});
  const [page, setPage] = useState(0);
  const [run, busy] = useAction();
  const api = useMemo(() => addonApi(id), [id]);
  const base = `/api/addons/${encodeURIComponent(id)}`;
  const steps = guided?.steps || [];
  const Intro = guided?.Intro;
  const check = guided?.check;
  const [checks, setChecks] = useState(null); // result of the check after saving page 1: null = not run yet
  const [checking, setChecking] = useState(false);
  const last = steps.length;
  const save = async () => {
    const result = await run(() => http.put(`${base}/settings`, { values }), (r) => r.message);
    if (result) onSaved();
    return Boolean(result);
  };
  /** Save the form, then (when the addon has a check) verify it: move on only if nothing failed. */
  const saveAndNext = async () => {
    if (!(await save())) return;
    if (!check) { setPage(1); return; }
    setChecking(true);
    setChecks(null);
    let result = null;
    // The addon may restart after a changed setting: ask again for a few seconds until it answers.
    for (let attempt = 0; attempt < 8 && !result; attempt += 1) {
      try { result = await check(api); } catch { await new Promise((resolve) => setTimeout(resolve, 1500)); }
    }
    setChecking(false);
    const list = result?.checks || [{ level: "fail", message: "Không kiểm tra được: addon chưa trả lời. Bấm Chạy ở đầu trang rồi thử lại." }];
    setChecks(list);
    if (!list.some((item) => item.level === "fail")) setPage(1);
  };
  // Opened for one field (the "fill in X" banner): put the cursor there, as Material does, instead of marking it.
  useEffect(() => {
    if (!focus) return;
    const timer = setTimeout(() => document.querySelector(`[data-setting="${CSS.escape(focus)}"] :is(md-outlined-text-field, md-outlined-select)`)?.focus(), 150);
    return () => clearTimeout(timer);
  }, [focus]);
  const Step = page > 0 ? steps[page - 1].Page : null;
  const name = data.label || data.name;
  return <Dialog wide icon="settings" onClose={onClose}
    headline={steps.length ? `Cài đặt ${name} · ${page + 1}/${last + 1}${page ? `: ${steps[page - 1].title}` : ""}` : `Cài đặt ${name}`}
    actions={(close) => !steps.length ? <><Button onClick={close}>Huỷ</Button>
      <Button variant="filled" icon="save" disabled={busy} onClick={async () => { if (await save()) close(); }}>Lưu</Button></>
      : page === 0 ? <><Button onClick={close}>Đóng</Button>
        <Button variant="filled" icon="arrow_forward" disabled={busy || checking} onClick={saveAndNext}>{checking ? "Đang kiểm tra…" : check ? "Lưu và kiểm tra" : "Lưu và tiếp"}</Button></>
      : <><Button icon="arrow_back" onClick={() => setPage(page - 1)}>Quay lại</Button>
        {page < last ? <Button variant="filled" icon="arrow_forward" onClick={() => setPage(page + 1)}>Tiếp</Button>
          : <Button variant="filled" icon="check" onClick={close}>Xong</Button>}</>}>
    {page === 0 ? <div className="md-stack vh-form">
      {Intro ? <Intro api={api} info={data} /> : null}
      {data.settings.map((setting) => <div key={setting.key} data-setting={setting.key}>
        <SettingField setting={setting} value={values[setting.key]}
          onChange={(value) => setValues((previous) => ({ ...previous, [setting.key]: value }))} />
      </div>)}
      {checks ? <div className="md-stack" style={{ gap: 8 }}>
        <Badge tone={checks.some((c) => c.level === "fail") ? "error" : checks.some((c) => c.level === "warn") ? "warning" : "success"}
          icon={checks.some((c) => c.level === "fail") ? "error" : "check_circle"}>
          {checks.some((c) => c.level === "fail") ? "Kiểm tra chưa đạt: sửa rồi lưu lại" : "Kiểm tra đạt"}</Badge>
        {checks.filter((c) => c.level !== "ok").map((c, index) => <div key={index} className="md-row" style={{ gap: 8, alignItems: "flex-start" }}>
          <md-icon style={{ color: c.level === "warn" ? "#f2a900" : "var(--md-sys-color-error)" }}>{c.level === "warn" ? "warning" : "error"}</md-icon>
          <div><div className="md-body-medium">{c.message}</div>{c.hint ? <div className="md-body-small md-muted">{c.hint}</div> : null}</div>
        </div>)}
      </div> : null}
    </div> : <div className="md-stack">
      {!data.running ? <Banner tone="warning" icon="power_settings_new">{name} đang dừng: bấm Chạy ở đầu trang rồi mở lại bước này.</Banner> : null}
      <Step api={api} info={data} />
    </div>}
  </Dialog>;
}

/** The service controls of a daemon (start / stop / restart, start with the Hub, MCP gateway) in a dialog. */
function ServiceDialog({ data, busy, act, flag, failure, onLog, onClose }) {
  const [tone, icon, trust] = TRUST[data.trust] || TRUST.unsigned;
  return <Dialog icon="dns" headline={`Dịch vụ ${data.label || data.name}`} onClose={onClose}
    actions={(close) => <Button onClick={close}>Đóng</Button>}>
    <div className="md-stack">
      <div className="md-row">
        {data.running ? <Badge tone="success" icon="check_circle">Đang chạy</Badge> : <Badge icon="pause_circle">Đã dừng</Badge>}
        <Badge>Phiên bản {data.version}</Badge>
        <Badge tone={tone} icon={icon}>{trust}</Badge>
        <Badge icon={data.runtime === "python" ? "code" : "javascript"}>{data.runtime === "python" ? "Python" : "Node.js"}</Badge>
      </div>
      <p className="md-card__subtitle">Dịch vụ chạy nền trên máy này và vẫn chạy khi đóng Viewer Hub.</p>
      <div className="md-row">
        {data.running ? <>
          <Button icon="restart_alt" disabled={busy} onClick={() => act("restart")}>Khởi động lại</Button>
          <Button icon="stop_circle" danger disabled={busy} onClick={() => act("stop")}>Dừng</Button>
        </> : <Button variant="filled" icon="play_arrow" disabled={busy || Boolean(data.problem)} onClick={() => act("start")}>Chạy</Button>}
        <span className="md-spacer"></span>
        <Button icon="receipt_long" onClick={onLog}>Nhật ký</Button>
      </div>
      <Switch selected={data.autostart} onChange={(on) => flag("autostart", on)}>Tự chạy khi mở Viewer Hub</Switch>
      {data.gateway !== null && data.gateway !== undefined
        ? <Switch selected={data.gateway} onChange={(on) => flag("gateway", on)}>Đăng ký MCP của Viewer Hub vào đây (tên viewer-…, chỉ tool đọc)</Switch>
        : null}
      {!data.running && failure.length ? <pre title="Lần chạy vừa rồi không thành công: cuối nhật ký" className="md-code" style={{ maxHeight: "30vh" }}>{failure.join("\n")}</pre> : null}
    </div>
  </Dialog>;
}

function Banner({ tone, icon, children, actions }) {
  return <div className={`md-banner${tone ? ` md-banner--${tone}` : ""}`} role={tone === "error" ? "alert" : "status"}>
    <md-icon>{icon}</md-icon><div className="md-banner__text">{children}</div>{actions}</div>;
}

/**
 * The Hub's part of every addon page: the page header (summary on the left; status, Nhật ký and Cài đặt on the right)
 * and a banner only when the user has something to do (start the service, open the program, fill in a setting, an
 * error). Settings and the service controls open in dialogs, so the addon's own page starts right below.
 * `onChange(info)` runs after each load; `onReady({ openSettings, reload })` once, for the frame (useAddon()).
 */
export function HubAddonPanel({ id, summary, onChange, onReady }) {
  const { data, reload } = useLoad(() => http.get(`/api/addons/${encodeURIComponent(id)}`), [id]);
  const [failure, setFailure] = useState([]);
  const [dialogOpen, setDialogOpen] = useState(null); // "log" | "service" | {settings: key}
  const [run, busy] = useAction();
  const [confirm, dialog] = useConfirm();
  const setup = useContext(FrameContext)?.setup;
  useEffect(() => {
    if (!data) return;
    if (data.running) setFailure([]);
    onChange?.(data);
  }, [data]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    onReady?.({ openSettings: (key) => setDialogOpen({ settings: key || null }), reload });
  }, [id]); // eslint-disable-line react-hooks/exhaustive-deps
  // Started / stopped elsewhere (its window closed, another tab, a crash): reload when the state changes.
  const running = data?.running;
  const watched = data?.lifecycle === "daemon" || data?.lifecycle === "external";
  useEffect(() => {
    if (running === undefined || !watched) return undefined;
    const timer = setInterval(() => {
      if (document.hidden) return;
      http.get(`/api/addons/${encodeURIComponent(id)}/status`).then((now) => { if (now.running !== running) reload(); }, () => {});
    }, POLL_MS);
    return () => clearInterval(timer);
  }, [id, running, watched]); // eslint-disable-line react-hooks/exhaustive-deps
  if (!data) return <>
    <PageHeader subtitle={summary} />
    <div style={{ padding: 16 }}><Skeleton count={4} /></div>
  </>;
  const base = `/api/addons/${encodeURIComponent(id)}`;
  const name = data.label || data.name;
  const daemon = data.lifecycle === "daemon";
  const external = data.lifecycle === "external";
  const act = async (action) => {
    if (action === "stop" && !(await confirm({
      title: `Dừng ${name}?`, confirm: "Dừng", icon: "stop_circle",
      text: "Dịch vụ dừng hẳn: các chương trình đang dùng nó (vd. Copilot Studio) mất kết nối cho tới khi chạy lại.",
    }))) return;
    if (action === "restart" && !(await confirm({
      title: `Khởi động lại ${name}?`, confirm: "Khởi động lại", icon: "restart_alt", danger: false,
      text: "Các request đang chạy có thể bị ngắt.",
    }))) return;
    try {
      const result = await http.post(`${base}/${action}`);
      window.md?.snackbar(result.message);
    } catch (error) {
      window.md?.snackbar(error.message);
      setFailure(error.body?.log || []);
    }
    reload();
  };
  const flag = (action, on) => run(() => http.post(`${base}/${action}`, { on }), (r) => r.message || (on ? "Đã bật" : "Đã tắt")).then(reload);
  const openSettings = (key) => setDialogOpen({ settings: key || null });
  const missing = (data.settings || []).filter((s) => s.required && !filled(data.values?.[s.key]));
  const status = daemon
    ? <button type="button" className={`vh-status${data.running ? " vh-status--success" : ""}`} title="Điều khiển dịch vụ"
      onClick={() => setDialogOpen("service")}>
      <md-icon>{data.running ? "check_circle" : "pause_circle"}</md-icon>{data.running ? "Đang chạy" : "Đã dừng"}
      <md-icon>arrow_drop_down</md-icon></button>
    : external
      ? <button type="button" className={`vh-status${data.running ? " vh-status--success" : " vh-status--warning"}`}
        title="Kiểm tra lại kết nối" onClick={reload}>
        <md-icon>{data.running ? "check_circle" : "link_off"}</md-icon>{data.running ? "Đã kết nối" : "Chưa kết nối"}</button>
      : null;
  return <>
    {dialog}
    {dialogOpen === "log" ? <LogDialog id={id} name={name} onClose={() => setDialogOpen(null)} /> : null}
    {dialogOpen === "service" ? <ServiceDialog data={data} busy={busy} act={act} flag={flag} failure={failure}
      onLog={() => setDialogOpen("log")} onClose={() => setDialogOpen(null)} /> : null}
    {dialogOpen?.settings !== undefined ? <SettingsDialog id={id} data={data} focus={dialogOpen.settings} setup={setup}
      onSaved={reload} onClose={() => setDialogOpen(null)} /> : null}
    <PageHeader subtitle={summary}>
      {status}
      {external ? null : <IconButton icon="receipt_long" label="Nhật ký" onClick={() => setDialogOpen("log")} />}
      {data.settings?.length ? <IconButton icon="settings" label="Cài đặt" onClick={() => openSettings()} /> : null}
    </PageHeader>
    {data.problem ? <Banner tone="error" icon="error"
      actions={external ? null : <Button icon="receipt_long" onClick={() => setDialogOpen("log")}>Nhật ký</Button>}>{data.problem}</Banner> : null}
    {!data.problem && daemon && !data.running ? <Banner icon="pause_circle"
      actions={<Button variant="filled" icon="play_arrow" disabled={busy} onClick={() => act("start")}>Chạy</Button>}>
      {name} đang dừng.{failure.length ? " Lần chạy vừa rồi không thành công: xem Nhật ký." : ""}</Banner> : null}
    {!data.problem && external && !data.running ? <Banner icon="link_off"
      actions={<><Button icon="refresh" onClick={reload}>Kiểm tra lại</Button><Button icon="settings" onClick={() => openSettings("port")}>Đổi cổng</Button></>}>
      Chưa thấy chương trình {data.name} ở <code>127.0.0.1:{data.port || "?"}</code>. Hãy mở chương trình đó (Viewer Hub không tự chạy nó).</Banner> : null}
    {data.deps?.state && data.deps.state !== "ok" ? <Banner tone={data.deps.state === "broken" ? "error" : null} icon="link_off">
      {data.deps.state === "broken" ? "Phần dùng dữ liệu của addon khác đang lỗi" : "Một tính năng tuỳ chọn đang tắt"}: {data.deps.reasons.join("; ")}.
      Cài / cập nhật addon được nhắc tới ở Cài đặt → Addon.</Banner> : null}
    {missing.length ? <Banner icon="edit_note"
      actions={<Button variant="filled" icon="settings" onClick={() => openSettings(missing[0].key)}>Mở cài đặt</Button>}>
      Cần điền {missing.map((s) => s.label).join(", ")} trước khi dùng.</Banner> : null}
  </>;
}

/** The addon page's view of the Hub's frame: { info, openSettings(key?), reload } (info null while loading). */
export function useAddon() {
  const frame = useContext(FrameContext);
  return { info: frame?.info ?? null, openSettings: (key) => frame?.control?.openSettings(key),
    reload: () => frame?.control?.reload() };
}
