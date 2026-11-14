// The page of an addon without its own UI (addon.json has no "ui"): the Hub's header (status, Nhật ký, Cài đặt) and
// the addon's GUIDE.md. The guide is the addon author's file rendered by the Hub, never user data.
import React, { useState } from "react";
import { HubAddonPanel } from "../addon.jsx";
import { useTitle } from "../context.jsx";

export default function AddonPage({ module }) {
  useTitle(module.label);
  const [info, setInfo] = useState(null);
  return <>
    <HubAddonPanel id={module.key} summary={module.summary} onChange={setInfo} />
    {info?.guide ? <section className="md-card md-card--outlined">
      <article className="md-card__body md-help__body" dangerouslySetInnerHTML={{ __html: info.guide }} />
    </section> : null}
  </>;
}
