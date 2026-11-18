// Page of the template addon "my-service" (lifecycle external): the program is the user's own (any language), the Hub
// relays `api` calls to it on 127.0.0.1:<port>. The Hub's header says whether it is connected (and shows what to do
// when it is not); this page only shows the program's data (as text, never as HTML).
// Do not redraw that header: no settings form or "not configured" banner, no Cài đặt / Nhật ký / run / stop buttons
// (refused at install). Settings live in addon/addon.json `settings` (+ `required`); open the Hub's dialog with
// useAddon().openSettings(key). See AGENTS.md, top of the file.
import React from "react";
import { ErrorBanner, Loading } from "@vh/md";
import { useLoad } from "@vh/ui";

export default function ServicePage({ api, addon }) {
  const connected = addon?.running;
  const { data, error } = useLoad(() => (connected ? api.get("/info") : Promise.resolve(null)), [connected]);
  if (!addon) return <Loading />;
  if (!connected) return null; // the Hub's banner above already says what to do
  return <div className="md-stack">
    {error ? <ErrorBanner>{error.message}</ErrorBanner> : null}
    {!data && !error ? <Loading /> : null}
    {data ? <section className="md-card md-card--outlined">
      <div className="md-card__body">
        <h2 className="md-card__title">{data.name}</h2>
        <p className="md-card__subtitle">Phiên bản {data.version} · {data.status}</p>
      </div>
    </section> : null}
  </div>;
}
