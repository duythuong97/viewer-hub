// Page of the template daemon addon "my-daemon". The Hub passes { module, subpath, api, addon } and draws the header
// and its panel above this page (run / stop / restart, settings, the daemon's whole log): `addon.running` says
// whether the daemon runs. `api` reaches its admin channel through the Hub (api.get("/state") → "GET /api/state"),
// and api.events() is its EVENTS stream as server-sent events.
// Do not redraw that header: no settings form or "not configured" banner, no Cài đặt / Nhật ký / run / stop buttons
// (refused at install). Settings live in addon.json `settings` (+ `required`); open the Hub's dialog with
// useAddon().openSettings(key). See AGENTS.md, top of the file.
import React, { useEffect, useState } from "react";
import { Button } from "@vh/md";
import { Badge, useAction, useConfirm, useTitle } from "@vh/ui";

export default function CounterPage({ module, api, addon }) {
  const running = Boolean(addon?.running);
  const [state, setState] = useState(null);
  const [run, busy] = useAction();
  const [confirm, dialog] = useConfirm(); // dangerous actions ask first (AGENTS.md §6.1)
  useTitle(module.label);
  const reset = async () => {
    if (!(await confirm({ title: "Đặt lại bộ đếm?", text: `Số đếm ${state.ticks} về 0.`, confirm: "Đặt lại", icon: "restart_alt" }))) return;
    const next = await run(() => api.post("/state/reset", {}), "Đã đặt lại");
    if (next) setState(next);
  };
  useEffect(() => {
    if (!running) { setState(null); return undefined; }
    api.get("/state").then(setState, () => setState(null));
    const source = api.events();
    source.addEventListener("tick", (event) => {
      const { ticks } = JSON.parse(event.data);
      setState((previous) => (previous ? { ...previous, ticks } : previous));
    });
    source.onerror = () => source.close();
    return () => source.close();
  }, [running, api]);
  return <>
    {dialog}
    <div className="md-stack">
      {state ? <section className="md-card md-card--outlined">
        <div className="md-card__body">
          <div className="md-row"><h2 className="md-card__title md-spacer">{state.name}</h2>
            <Badge tone="success" icon="timer">Đang đếm</Badge></div>
          <p className="md-card__subtitle">Từ {new Date(state.startedAt).toLocaleString()} · mỗi {state.interval} giây</p>
          <p className="md-display-small">{state.ticks}</p>
        </div>
        <div className="md-card__actions">
          <Button icon="restart_alt" danger disabled={busy} onClick={reset}>Đặt lại</Button>
        </div>
      </section> : null}
    </div>
  </>;
}
