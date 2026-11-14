// Giám sát: MCP calls AI makes (builtin modules and addons), their errors, speed and size, the AI clients, and the
// addons' health. API: viewer_hub/monitor/routes.py over monitor.db (viewer_hub/core/monitor.py).
import React, { useEffect, useMemo, useRef, useState } from "react";
import { Button, Dialog, Empty, ErrorBanner, IconButton, Loading, Segmented, Select, Switch, Tabs, TextField } from "../../md/react.jsx";
import { useLayout, useTitle } from "../../app/context.jsx";
import { http } from "../../app/http.js";
import { Link } from "../../app/router.jsx";
import { Badge, PageHeader, useAction, useConfirm, useLoad } from "../../app/ui.jsx";
import "./monitor.css";

const API = "/monitor/api";
const RANGES = [["1", "1 giờ"], ["6", "6 giờ"], ["24", "24 giờ"], ["168", "7 ngày"], ["336", "14 ngày"]];
const TABS = [["overview", "Tổng quan", "dashboard"], ["calls", "Lời gọi", "list"], ["tools", "Theo tool", "build"],
  ["addons", "Addon", "extension"]];
const LIVE_EVERY = 3000;
const ARGS_MODES = [["keys", "Chỉ tên và độ dài tham số (mặc định)"], ["full", "Đầy đủ tham số (gỡ lỗi)"], ["off", "Không lưu tham số"]];
const EVENT_TEXT = { start: "chạy", stop: "dừng", crash: "dừng bất thường", start_failed: "không chạy được", "log-flood": "ghi log quá nhiều" };

// ── formatting ─────────────────────────────────────────────────────────────────────────────────────────────────
const num = (n) => (n ?? 0).toLocaleString("vi-VN");
const ms = (v) => (v == null ? "–" : v >= 1000 ? `${(v / 1000).toFixed(v >= 10000 ? 0 : 1)} s` : `${Math.round(v)} ms`);
const pct = (v) => `${(v * 100).toFixed(v && v < 0.1 ? 1 : 0)}%`;
const bytes = (v) => (v == null ? "–" : v >= 1 << 30 ? `${(v / (1 << 30)).toFixed(1)} GB` : `${Math.round(v / (1 << 20))} MB`);
const clock = (at) => new Date(at * 1000).toLocaleTimeString("vi-VN", { hour12: false });
const stamp = (at) => new Date(at * 1000).toLocaleString("vi-VN", { hour12: false });
function ago(at) {
  if (!at) return "–";
  const s = Math.max(0, Date.now() / 1000 - at);
  if (s < 60) return "vừa xong";
  if (s < 3600) return `${Math.floor(s / 60)} phút trước`;
  if (s < 86400) return `${Math.floor(s / 3600)} giờ trước`;
  return `${Math.floor(s / 86400)} ngày trước`;
}
const label = (labels, key) => labels?.[key] || key;

// ── pieces ─────────────────────────────────────────────────────────────────────────────────────────────────────
function Alerts({ alerts, labels }) {
  if (!alerts?.length) return null;
  return <div className="md-stack mo-alerts">
    {alerts.map((a, i) => <div key={i} className={`md-banner${a.level === "error" ? " md-banner--error" : " mo-banner--warning"}`} role={a.level === "error" ? "alert" : "status"}>
      <md-icon>{a.level === "error" ? "error" : "warning"}</md-icon>
      <div className="md-banner__text"><b>{label(labels, a.source)}</b>: {a.message}</div>
    </div>)}
  </div>;
}

function Tile({ icon, title, value, sub, tone }) {
  return <div className={`md-card md-card--outlined mo-tile${tone ? ` mo-tile--${tone}` : ""}`}>
    <div className="mo-tile__head"><md-icon>{icon}</md-icon>{title}</div>
    <div className="mo-tile__value">{value}</div>
    {sub ? <div className="mo-tile__sub">{sub}</div> : null}
  </div>;
}

/** Calls per hour, errors stacked on top (status colour + legend + hover text: never colour alone). */
function HourChart({ series }) {
  const [hover, setHover] = useState(null);
  const [width, setWidth] = useState(720);
  const box = useRef(null);
  useEffect(() => {  // draw at the real pixel width so the axis text keeps its size
    const el = box.current;
    if (!el || typeof ResizeObserver === "undefined") return undefined;
    const observer = new ResizeObserver(([entry]) => setWidth(Math.max(240, Math.round(entry.contentRect.width))));
    observer.observe(el);
    return () => observer.disconnect();
  }, []);
  const height = 200, pad = { l: 36, r: 8, t: 8, b: 22 };
  const max = Math.max(1, ...series.map((s) => s.calls));
  const step = (width - pad.l - pad.r) / Math.max(1, series.length);
  const bar = Math.max(2, step - 2);
  const y = (v) => pad.t + (height - pad.t - pad.b) * (1 - v / max);
  const ticks = [0, Math.ceil(max / 2), max];
  const every = Math.max(1, Math.ceil(series.length / 8));
  const showDay = series.length > 24;
  const tickText = (at) => {
    const d = new Date(at * 1000);
    return showDay ? `${d.getDate()}/${d.getMonth() + 1}` : `${d.getHours()}h`;
  };
  const point = hover != null ? series[hover] : null;
  return <div className="mo-chart" ref={box}>
    <div className="mo-legend">
      <span><i className="mo-key mo-key--ok" />Lời gọi thành công</span>
      <span><i className="mo-key mo-key--err" /><md-icon>error</md-icon>Lỗi</span>
      <span className="mo-chart__hover">{point ? `${stamp(point.hour)} · ${num(point.calls)} lời gọi, ${num(point.errors)} lỗi` : "Rê chuột lên cột để xem số"}</span>
    </div>
    <svg viewBox={`0 0 ${width} ${height}`} width={width} height={height} role="img" aria-label="Số lời gọi MCP theo giờ" onMouseLeave={() => setHover(null)}>
      {ticks.map((t) => <g key={t}>
        <line x1={pad.l} x2={width - pad.r} y1={y(t)} y2={y(t)} className="mo-grid" />
        <text x={pad.l - 6} y={y(t) + 4} className="mo-axis" textAnchor="end">{t}</text>
      </g>)}
      {series.map((s, i) => {
        const x = pad.l + i * step + 1;
        const ok = s.calls - s.errors;
        return <g key={s.hour} onMouseEnter={() => setHover(i)}>
          <rect x={x - 1} y={pad.t} width={step} height={height - pad.t - pad.b} fill="transparent" />
          {ok > 0 ? <rect x={x} y={y(ok)} width={bar} height={Math.max(1, y(0) - y(ok))} rx="2"
            className={`mo-bar${hover === i ? " mo-bar--on" : ""}`} /> : null}
          {s.errors > 0 ? <rect x={x} y={y(s.calls)} width={bar} height={Math.max(1, y(ok) - y(s.calls) - (ok ? 2 : 0))} rx="2"
            className={`mo-bar mo-bar--err${hover === i ? " mo-bar--on" : ""}`} /> : null}
          {i % every === 0 ? <text x={x + bar / 2} y={height - 6} className="mo-axis" textAnchor="middle">{tickText(s.hour)}</text> : null}
        </g>;
      })}
    </svg>
  </div>;
}

function Table({ columns, rows, rowKey, onRow, empty = "Chưa có dữ liệu", initialSort }) {
  const [sort, setSort] = useState(initialSort || null);
  const sorted = useMemo(() => {
    if (!sort) return rows;
    const col = columns.find((c) => c.key === sort[0]);
    const value = col?.sort || ((r) => r[sort[0]]);
    return [...rows].sort((a, b) => {
      const x = value(a), z = value(b);
      return (x > z ? 1 : x < z ? -1 : 0) * (sort[1] ? -1 : 1);
    });
  }, [rows, sort, columns]);
  if (!rows.length) return <p className="md-body-medium md-muted mo-empty">{empty}</p>;
  return <div className="md-table-wrap mo-table">
    <table className="md-table">
      <thead><tr>{columns.map((c) => <th key={c.key} className={c.num ? "md-table__num" : undefined}>
        <button type="button" className="mo-sort" onClick={() => setSort(sort?.[0] === c.key ? [c.key, !sort[1]] : [c.key, true])}>
          {c.title}{sort?.[0] === c.key ? <md-icon>{sort[1] ? "arrow_downward" : "arrow_upward"}</md-icon> : null}
        </button></th>)}</tr></thead>
      <tbody>{sorted.map((r) => <tr key={rowKey(r)} className={onRow ? "md-table__row--link" : undefined} onClick={onRow ? () => onRow(r) : undefined}>
        {columns.map((c) => <td key={c.key} className={c.num ? "md-table__num" : undefined}>{c.render ? c.render(r) : r[c.key]}</td>)}
      </tr>)}</tbody>
    </table>
  </div>;
}

function Status({ ok, error }) {
  return ok ? <Badge tone="success" icon="check">OK</Badge> : <span title={error}><Badge tone="error" icon="error">Lỗi</Badge></span>;
}

// ── tabs ───────────────────────────────────────────────────────────────────────────────────────────────────────
function Overview({ data, hours }) {
  const { totals, labels } = data;
  const serverCols = [
    { key: "server", title: "MCP", render: (r) => label(labels, r.server), sort: (r) => label(labels, r.server) },
    { key: "calls", title: "Lời gọi", num: true, render: (r) => num(r.calls) },
    { key: "errors", title: "Lỗi", num: true, render: (r) => r.errors ? <span className="mo-bad">{num(r.errors)}</span> : 0 },
    { key: "avgMs", title: "TB", num: true, render: (r) => ms(r.avgMs) },
    { key: "tokens", title: "~Token", num: true, render: (r) => num(r.tokens) },
    { key: "last", title: "Gọi cuối", render: (r) => ago(r.last) },
  ];
  const clientCols = [
    { key: "client", title: "AI / client" },
    { key: "transport", title: "Kết nối", render: (r) => <>{r.transport === "stdio" ? "stdio" : "HTTP"}{r.via && r.via !== r.client ? <span className="md-muted"> · qua {r.via}</span> : null}</> },
    { key: "calls", title: "Lời gọi", num: true, render: (r) => num(r.calls) },
    { key: "last", title: "Lần cuối", render: (r) => <span title={stamp(r.last)}>{ago(r.last)}</span> },
  ];
  return <div className="md-stack">
    <div className="mo-tiles">
      <Tile icon="call_made" title="Lời gọi" value={num(totals.calls)} sub={`${RANGES.find(([h]) => Number(h) === hours)?.[1] || ""} qua`} />
      <Tile icon="error" title="Lỗi" value={num(totals.errors)} sub={totals.calls ? `${pct(totals.errorRate)} số lời gọi` : "–"} tone={totals.errorRate >= 0.2 ? "bad" : undefined} />
      <Tile icon="speed" title="Thời gian trả lời" value={ms(totals.p50Ms)} sub={`p95: ${ms(totals.p95Ms)}`} />
      <Tile icon="token" title="Token trả cho AI" value={`~${num(totals.tokens)}`} sub="ước tính: số ký tự / 4" />
      <Tile icon="smart_toy" title="AI đã gọi" value={num(totals.clients)} sub="client khác nhau" />
    </div>
    <section className="md-card md-card--outlined"><div className="md-card__body md-stack">
      <div className="md-title-medium">Lời gọi theo giờ</div>
      <HourChart series={data.series} />
    </div></section>
    <div className="mo-two">
      <section className="md-stack"><div className="md-title-medium">Theo MCP</div>
        <Table columns={serverCols} rows={data.servers} rowKey={(r) => r.server} initialSort={["calls", true]} empty="Chưa có lời gọi nào trong khoảng này" /></section>
      <section className="md-stack"><div className="md-title-medium">AI đã kết nối (30 ngày)</div>
        <Table columns={clientCols} rows={data.clients} rowKey={(r) => `${r.client}|${r.transport}|${r.via}`} initialSort={["last", true]} empty="Chưa có AI nào kết nối" /></section>
    </div>
    <section className="md-stack"><div className="md-title-medium">Sự kiện của addon</div>
      {data.events.length ? <ul className="mo-events">{data.events.map((e) => <li key={e.id} className={`mo-event mo-event--${e.level}`}>
        <md-icon>{e.level === "error" ? "error" : e.level === "warning" ? "warning" : "info"}</md-icon>
        <span className="mo-event__time" title={stamp(e.at)}>{ago(e.at)}</span>
        <b>{label(labels, e.source)}</b> {EVENT_TEXT[e.kind] || e.kind}<span className="md-muted"> · {e.message}</span>
      </li>)}</ul> : <p className="md-body-medium md-muted mo-empty">Chưa có sự kiện</p>}
    </section>
  </div>;
}

function CallDialog({ call, labels, onClose }) {
  let args = call.args;
  try { args = JSON.stringify(JSON.parse(call.args), null, 2); } catch { /* keep the text */ }
  return <Dialog icon="call_made" headline={`${label(labels, call.server)} · ${call.tool}`} onClose={onClose}
    actions={(close) => <Button onClick={close}>Đóng</Button>}>
    <dl className="mo-detail">
      <dt>Thời điểm</dt><dd>{stamp(call.at)}</dd>
      <dt>Kết quả</dt><dd><Status ok={call.ok} error={call.error} /></dd>
      <dt>AI / client</dt><dd>{call.client} · {call.transport === "stdio" ? "stdio" : "HTTP"}{call.via && call.via !== call.client ? ` · qua ${call.via}` : ""}</dd>
      <dt>Thời gian</dt><dd>{ms(call.ms)}</dd>
      <dt>Trả về</dt><dd>{num(call.outChars)} ký tự (~{num(call.tokens)} token)</dd>
      {call.error ? <><dt>Lỗi</dt><dd><pre className="mo-pre">{call.error}</pre></dd></> : null}
      <dt>Tham số</dt><dd>{args ? <pre className="mo-pre">{args}</pre> : <span className="md-muted">không lưu (Cài đặt)</span>}</dd>
    </dl>
  </Dialog>;
}

function Calls() {
  const [filter, setFilter] = useState({ server: "", client: "", errors: false });
  const [rows, setRows] = useState([]);
  const [meta, setMeta] = useState({ clients: [], labels: {} });
  const [paused, setPaused] = useState(false);
  const [error, setError] = useState(null);
  const [open, setOpen] = useState(null);
  const latest = useRef(0);
  const params = (extra) => ({ server: filter.server, client: filter.client, errors: filter.errors ? "1" : "", ...extra });
  useEffect(() => {
    let alive = true;
    latest.current = 0;
    setRows([]);
    const load = async () => {
      try {
        const data = await http.get(`${API}/calls`, params({ since: latest.current || "", limit: 300 }));
        if (!alive) return;
        setError(null);
        setMeta({ clients: data.clients, labels: data.labels });
        if (data.calls.length) {
          latest.current = data.calls[0].id;
          setRows((old) => [...data.calls, ...old].slice(0, 1000));
        }
      } catch (err) { if (alive) setError(err); }
    };
    load();
    const timer = paused ? null : setInterval(load, LIVE_EVERY);
    return () => { alive = false; if (timer) clearInterval(timer); };
  }, [filter, paused]); // eslint-disable-line react-hooks/exhaustive-deps
  const servers = [...new Set(rows.map((r) => r.server))];
  const cols = [
    { key: "at", title: "Lúc", render: (r) => <span title={stamp(r.at)}>{clock(r.at)}</span> },
    { key: "tool", title: "MCP · tool", render: (r) => <><span className="md-muted">{label(meta.labels, r.server)} · </span>{r.tool}</> },
    { key: "client", title: "AI / client", render: (r) => <>{r.client}{r.via && r.via !== r.client ? <span className="md-muted"> · qua {r.via}</span> : null}</> },
    { key: "ms", title: "Thời gian", num: true, render: (r) => <span className={r.ms > 10000 ? "mo-bad" : undefined}>{ms(r.ms)}</span> },
    { key: "outChars", title: "~Token", num: true, render: (r) => num(r.tokens) },
    { key: "ok", title: "Kết quả", render: (r) => <Status ok={r.ok} error={r.error} /> },
  ];
  return <div className="md-stack">
    {open ? <CallDialog call={open} labels={meta.labels} onClose={() => setOpen(null)} /> : null}
    <div className="md-row mo-filters">
      <Select label="MCP" value={filter.server} onChange={(v) => setFilter({ ...filter, server: v })}
        options={[["", "Tất cả MCP"], ...[...new Set([...servers, filter.server].filter(Boolean))].map((s) => [s, label(meta.labels, s)])]} />
      <Select label="AI / client" value={filter.client} onChange={(v) => setFilter({ ...filter, client: v })}
        options={[["", "Tất cả"], ...meta.clients.filter((c, i, all) => all.indexOf(c) === i).map((c) => [c, c])]} />
      <Switch selected={filter.errors} onChange={(v) => setFilter({ ...filter, errors: v })}>Chỉ lỗi</Switch>
      <span className="md-spacer" />
      {paused ? <Badge tone="warning" icon="pause">Đã tạm dừng</Badge> : <Badge tone="success" icon="sensors">Đang cập nhật</Badge>}
      <IconButton icon={paused ? "play_arrow" : "pause"} label={paused ? "Tiếp tục cập nhật" : "Tạm dừng cập nhật"} onClick={() => setPaused(!paused)} />
    </div>
    {error ? <ErrorBanner>{error.message}</ErrorBanner> : null}
    <Table columns={cols} rows={rows} rowKey={(r) => r.id} onRow={setOpen}
      empty={filter.errors ? "Không có lời gọi lỗi" : "Chưa có lời gọi nào. Khi AI dùng một MCP của Viewer Hub, lời gọi hiện ở đây."} />
  </div>;
}

function Tools({ hours }) {
  const { data, error } = useLoad(() => http.get(`${API}/tools`, { hours }), [hours]);
  if (error) return <ErrorBanner>{error.message}</ErrorBanner>;
  if (!data) return <Loading />;
  const cols = [
    { key: "tool", title: "MCP · tool", render: (r) => <><span className="md-muted">{label(data.labels, r.server)} · </span>{r.tool}</>, sort: (r) => `${r.server}.${r.tool}` },
    { key: "calls", title: "Lời gọi", num: true, render: (r) => num(r.calls) },
    { key: "errors", title: "Lỗi", num: true, render: (r) => r.errors ? <span className="mo-bad">{num(r.errors)} ({pct(r.errors / r.calls)})</span> : 0 },
    { key: "p50Ms", title: "p50", num: true, render: (r) => ms(r.p50Ms) },
    { key: "p95Ms", title: "p95", num: true, render: (r) => <span className={r.p95Ms > 10000 ? "mo-bad" : undefined}>{ms(r.p95Ms)}</span> },
    { key: "maxMs", title: "Lâu nhất", num: true, render: (r) => ms(r.maxMs) },
    { key: "avgOut", title: "Cỡ TB (ký tự)", num: true, render: (r) => num(r.avgOut) },
    { key: "tokens", title: "~Token tổng", num: true, render: (r) => num(r.tokens) },
    { key: "last", title: "Gọi cuối", render: (r) => ago(r.last) },
  ];
  return <div className="md-stack">
    <p className="md-body-medium md-muted">p50 / p95: một nửa / 95% lời gọi nhanh hơn mức này. Bấm tiêu đề cột để sắp xếp; tool trả về quá dài làm AI tốn context.</p>
    <Table columns={cols} rows={data.tools} rowKey={(r) => `${r.server}.${r.tool}`} initialSort={["calls", true]} empty="Chưa có lời gọi nào trong khoảng này" />
  </div>;
}

function Spark({ samples, field, format }) {
  const values = samples.map((s) => s[field]).filter((v) => v != null);
  if (values.length < 2) return <span className="md-muted">{values.length ? format(values[0]) : "–"}</span>;
  const max = Math.max(...values) || 1, w = 120, h = 28;
  const points = values.map((v, i) => `${(i / (values.length - 1)) * w},${h - 2 - (v / max) * (h - 4)}`).join(" ");
  return <span className="mo-spark" title={`cao nhất ${format(max)}`}>
    <svg viewBox={`0 0 ${w} ${h}`} width={w} height={h} aria-hidden="true"><polyline points={points} /></svg>
    <b>{format(values[values.length - 1])}</b>
  </span>;
}

function GatewayStats({ stats }) {
  if (!stats) return null;
  const tools = stats.tools || [];
  return <div className="md-stack mo-gateway">
    <div className="md-title-small">Lời gọi nó nhận trong {stats.hours || 24} giờ: {num(stats.requests?.total)} request, {num(stats.calls?.total)} lời gọi tool
      {stats.calls?.errors ? <span className="mo-bad">, {num(stats.calls.errors)} lỗi</span> : null}</div>
    {tools.length ? <Table rows={tools.slice(0, 15)} rowKey={(r) => `${r.server}.${r.tool}`} initialSort={["calls", true]} columns={[
      { key: "tool", title: "Server · tool", render: (r) => <><span className="md-muted">{r.server} · </span>{r.tool}</> },
      { key: "calls", title: "Lời gọi", num: true, render: (r) => num(r.calls) },
      { key: "errors", title: "Lỗi", num: true, render: (r) => r.errors ? <span className="mo-bad">{num(r.errors)}</span> : 0 },
      { key: "p95Ms", title: "p95", num: true, render: (r) => ms(r.p95Ms) },
    ]} /> : null}
  </div>;
}

function Addons() {
  const { data, error, reload } = useLoad(() => http.get(`${API}/addons`), []);
  useEffect(() => { const t = setInterval(reload, 30000); return () => clearInterval(t); }, []); // eslint-disable-line react-hooks/exhaustive-deps
  if (error) return <ErrorBanner>{error.message}</ErrorBanner>;
  if (!data) return <Loading />;
  return <div className="mo-addons">
    {data.addons.map((a) => {
      const last = a.samples[a.samples.length - 1];
      return <section key={a.id} className="md-card md-card--outlined"><div className="md-card__body md-stack">
        <div className="md-row">
          <span className="md-title-medium">{a.name}</span>
          {a.lifecycle !== "hub" ? <Badge>{a.lifecycle === "daemon" ? "chạy nền" : a.lifecycle === "external" ? "chương trình ngoài" : "Hub chạy khi cần"}</Badge> : null}
          <span className="md-spacer" />
          {a.problem ? <Badge tone="error" icon="block">{a.problem}</Badge>
            : a.running ? <Badge tone="success" icon="check_circle">Đang chạy</Badge> : <Badge icon="pause_circle">Không chạy</Badge>}
        </div>
        <div className="mo-kv">
          <span>RAM</span><Spark samples={a.samples} field="rss" format={bytes} />
          <span>CPU</span><Spark samples={a.samples} field="cpu" format={(v) => `${v.toFixed(1)}%`} />
          {a.id !== "hub" ? <><span>Dừng bất thường 24 giờ</span><b className={a.crashes ? "mo-bad" : undefined}>{a.crashes || 0}</b></> : null}
          {a.mcp ? <><span>MCP</span><span>{a.mcp}</span></> : null}
          {last ? <><span>Đo lúc</span><span>{clock(last.at)}</span></> : null}
        </div>
        {a.events?.length ? <ul className="mo-events mo-events--small">{a.events.slice(0, 5).map((e) => <li key={e.id} className={`mo-event mo-event--${e.level}`}>
          <span className="mo-event__time" title={stamp(e.at)}>{ago(e.at)}</span>{EVENT_TEXT[e.kind] || e.kind}
          <span className="md-muted"> · {e.message}</span></li>)}</ul> : null}
        <GatewayStats stats={a.gateway} />
        {a.id !== "hub" ? <div><Link to={`/x/${a.id}`}><Button icon="description">Mở trang addon (nhật ký, cài đặt)</Button></Link></div> : null}
      </div></section>;
    })}
  </div>;
}

function SettingsDialog({ settings, onClose, onSaved }) {
  const [form, setForm] = useState({ enabled: settings.enabled !== "0", args: settings.args, retention_days: settings.retention_days });
  const [run, busy] = useAction();
  const [confirm, dialog] = useConfirm();
  const save = async (close) => { if (await run(() => http.put(`${API}/settings`, form), (r) => r.message)) { onSaved(); close(); } };
  const clear = async () => {
    if (!(await confirm({ title: "Xoá toàn bộ dữ liệu giám sát?", text: "Mọi lời gọi, số liệu theo giờ, sự kiện và số đo RAM / CPU đã lưu bị xoá. Không hoàn tác được.", confirm: "Xoá", icon: "delete_sweep" }))) return;
    if (await run(() => http.post(`${API}/clear`), (r) => r.message)) onSaved();
  };
  return <>
    {dialog}
    <Dialog icon="tune" headline="Cài đặt giám sát" onClose={onClose}
      actions={(close) => <><Button icon="delete_sweep" danger disabled={busy} onClick={clear}>Xoá dữ liệu</Button><span className="md-spacer" />
        <Button onClick={close}>Huỷ</Button><Button variant="filled" icon="save" disabled={busy} onClick={() => save(close)}>Lưu</Button></>}>
      <div className="md-stack vh-form">
        <Switch selected={form.enabled} onChange={(v) => setForm({ ...form, enabled: v })}>Ghi lại lời gọi MCP và sự kiện addon</Switch>
        <Select label="Tham số của lời gọi" value={form.args} onChange={(v) => setForm({ ...form, args: v })} options={ARGS_MODES} />
        <p className="md-body-small md-muted">Kết quả trả về không bao giờ được lưu, chỉ lưu độ dài. "Đầy đủ" lưu cả giá trị AI gửi (tối đa 2000 ký tự), chỉ nên bật khi cần gỡ lỗi.</p>
        <TextField label="Giữ chi tiết lời gọi (ngày)" type="number" value={String(form.retention_days)} onChange={(v) => setForm({ ...form, retention_days: v })}
          supportingText="1 – 90 ngày. Số liệu theo giờ giữ 90 ngày." />
      </div>
    </Dialog>
  </>;
}

export default function MonitorPage() {
  useTitle("Giám sát");
  useLayout("wide");
  const [tab, setTab] = useState("overview");
  const [hours, setHours] = useState(24);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const { data, error, reload } = useLoad(() => http.get(`${API}/overview`, { hours }), [hours]);
  useEffect(() => { const t = setInterval(reload, 30000); return () => clearInterval(t); }, [hours]); // eslint-disable-line react-hooks/exhaustive-deps
  const off = data?.settings?.enabled === "0";
  return <>
    {settingsOpen && data ? <SettingsDialog settings={data.settings} onClose={() => setSettingsOpen(false)} onSaved={reload} /> : null}
    <PageHeader subtitle="AI dùng MCP nào (cả addon), lỗi, độ chậm, token trả về, và sức khoẻ của addon. Mọi số liệu nằm trên máy này.">
      <IconButton icon="refresh" label="Tải lại" onClick={reload} />
      <IconButton icon="tune" label="Cài đặt giám sát" onClick={() => setSettingsOpen(true)} />
    </PageHeader>
    {off ? <div className="md-banner" role="status"><md-icon>pause_circle</md-icon>
      <div className="md-banner__text">Đang tắt giám sát: lời gọi mới không được ghi.</div>
      <md-text-button onClick={() => setSettingsOpen(true)}>Bật lại</md-text-button></div> : null}
    <Alerts alerts={data?.alerts} labels={data?.labels} />
    <div className="md-row mo-bar-top">
      <Tabs tabs={TABS} value={tab} onChange={setTab} className="mo-tabs" />
      <span className="md-spacer" />
      {tab === "overview" || tab === "tools" ? <Segmented dense label="Khoảng thời gian" options={RANGES} value={String(hours)} onChange={(v) => setHours(Number(v))} /> : null}
    </div>
    {error ? <ErrorBanner>{error.message}</ErrorBanner> : null}
    {tab === "overview" ? (data ? <Overview data={data} hours={hours} /> : error ? null : <Loading />) : null}
    {tab === "calls" ? <Calls /> : null}
    {tab === "tools" ? <Tools hours={hours} /> : null}
    {tab === "addons" ? <Addons /> : null}
    {data && !data.totals.calls && tab === "overview" && !data.clients.length
      ? <Empty icon="monitoring" title="Chưa có lời gọi MCP nào">Kết nối AI với một MCP của Viewer Hub (địa chỉ ở trang Hướng dẫn); mỗi lần AI gọi tool sẽ hiện ở đây.</Empty> : null}
  </>;
}
