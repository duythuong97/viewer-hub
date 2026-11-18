// The frame of an addon page with its own UI (addon.json "ui"): the Hub draws the page header with its controls
// (status, Nhật ký, Cài đặt; banners when the user must act), then the addon's page below. The addon page gets the
// panel's info as `addon` ({ running, values, version, … }) and useAddon() from "@vh/ui" (openSettings, reload); it
// never draws run / stop / log / settings itself, and when it throws or fails to load, the header stays usable.
import React, { Suspense, lazy, useState } from "react";
import { FrameContext, HubAddonPanel } from "../addon.jsx";
import { useTitle } from "../context.jsx";

class AddonBoundary extends React.Component {
  constructor(props) { super(props); this.state = { error: null }; }
  static getDerivedStateFromError(error) { return { error }; }
  render() {
    if (!this.state.error) return this.props.children;
    return <div className="md-banner md-banner--error" role="alert"><md-icon>error</md-icon>
      <div className="md-banner__text">Trang của addon bị lỗi: {String(this.state.error.message || this.state.error)}.
        Nhật ký và cài đặt ở trên vẫn dùng được.</div></div>;
  }
}

/** The menu label as the page title; rendered before the addon page so the page's own useTitle wins. */
function DefaultTitle({ title }) {
  useTitle(title);
  return null;
}

/** A page component that shows the addon's page (`load()` imports its module) inside the Hub's frame. The module's
 *  `setup` export ([{ title, Page }]) turns the settings dialog into a guided setup, and `setupIntro` (a component, optional)
 *  is shown above the settings form on its first page; `setupCheck(api)` (async, optional) runs after the form is saved and
 *  returns { checks: [{ level: ok|warn|fail, message, hint? }] }: the setup moves on only when nothing failed (SettingsDialog in addon.jsx). */
export function framed(load) {
  const holder = { setup: null, listener: null };
  const Inner = lazy(() => load().then((module) => {
    holder.setup = Array.isArray(module.setup) && module.setup.length ? { steps: module.setup, Intro: module.setupIntro || null, check: module.setupCheck || null } : null;
    holder.listener?.(holder.setup);
    return module;
  }));
  return function AddonFrame({ module, subpath, api }) {
    const [info, setInfo] = useState(null);
    const [control, setControl] = useState(null);
    const [setup, setSetup] = useState(holder.setup);
    holder.listener = setSetup;
    return <FrameContext.Provider value={{ id: module.key, info, control, setup }}>
      <DefaultTitle title={module.label} />
      <HubAddonPanel id={module.key} summary={module.summary} onChange={setInfo} onReady={setControl} />
      <AddonBoundary>
        <Suspense fallback={<md-linear-progress indeterminate></md-linear-progress>}>
          <Inner module={module} subpath={subpath} api={api} addon={info} />
        </Suspense>
      </AddonBoundary>
    </FrameContext.Provider>;
  };
}
