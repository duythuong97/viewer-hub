// The frame of every page: navigation rail, top app bar (section title + theme), read-only banner, page body.
import React, { Suspense, useCallback, useEffect, useMemo, useState } from "react";
import { cycleTheme, currentTheme } from "../md/theme.js";
import { AppContext } from "./context.jsx";
import { addonApi, http } from "./http.js";
import { NotFound, resolve } from "./pages.js";
import { Link, useRouter } from "./router.jsx";

const THEME_ICON = { light: "light_mode", dark: "dark_mode", system: "brightness_auto" };
const THEME_TEXT = { light: "Giao diện sáng", dark: "Giao diện tối", system: "Theo hệ thống" };

function NavItem({ item, current, dot }) {
  return <Link to={item.path} className="md-nav-item" aria-current={current ? "page" : undefined}>
    <span className="md-nav-item__indicator"><md-icon>{item.icon}</md-icon></span>
    {dot ? <span className="md-nav-item__dot" title={dot} aria-label={dot}></span> : null}
    <span>{item.label}</span>
  </Link>;
}

// Giám sát: how many alerts (failing MCP, crashing addon) to show as a dot on its menu entry; asked every minute.
function useMonitorAlerts(app) {
  const [count, setCount] = useState(0);
  const enabled = app.nav.some((item) => item.key === "monitor");
  useEffect(() => {
    if (!enabled) return undefined;
    let alive = true;
    const load = () => http.get("/monitor/api/alerts").then((r) => alive && setCount(r.alerts.length), () => {});
    load();
    const timer = setInterval(load, 60000);
    return () => { alive = false; clearInterval(timer); };
  }, [enabled]);
  return count;
}

function isCurrent(item, path) {
  if (item.path === "/") return path === "/";
  return path === item.path || path.startsWith(item.path + "/");
}

// A page that throws (an addon's page above all) shows a banner; the menu and every other page keep working.
class Boundary extends React.Component {
  constructor(props) { super(props); this.state = { error: null }; }
  static getDerivedStateFromError(error) { return { error }; }
  componentDidUpdate(previous) { if (previous.path !== this.props.path && this.state.error) this.setState({ error: null }); }
  render() {
    if (!this.state.error) return this.props.children;
    return <div className="md-empty"><md-icon>error</md-icon><h2>{this.props.addon ? "Trang của addon bị lỗi" : "Trang bị lỗi"}</h2>
      <p>{String(this.state.error.message || this.state.error)}</p></div>;
  }
}

export default function Shell({ app, reload }) {
  const { path } = useRouter();
  const [title, setTitleState] = useState("Viewer Hub");
  const [theme, setTheme] = useState(currentTheme());
  const [scrolled, setScrolled] = useState(false);
  const setTitle = useCallback((value) => setTitleState(value || "Viewer Hub"), []);
  const [layout, setLayout] = useState("page");
  useEffect(() => {
    const update = () => setScrolled(window.scrollY > 0);
    window.addEventListener("scroll", update, { passive: true });
    return () => window.removeEventListener("scroll", update);
  }, []);
  const { Page, module, subpath } = resolve(path, app);
  const alerts = useMonitorAlerts(app);
  const api = useMemo(() => (module?.addon ? addonApi(module.key) : undefined), [module?.addon, module?.key]);
  return <AppContext.Provider value={{ app, setTitle, setLayout, reload }}>
    <div className="md-app">
      <nav className="md-nav-rail" aria-label="Điều hướng chính">
        <Link to="/" className="md-nav-rail__brand" aria-label="Viewer Hub"><md-icon filled>dashboard</md-icon></Link>
        <div className="md-nav-rail__items">
          {app.nav.map((item) => <NavItem key={item.key} item={item} current={isCurrent(item, path)}
            dot={item.key === "monitor" && alerts ? `${alerts} cảnh báo` : null} />)}
        </div>
        <div className="md-nav-rail__spacer"></div>
        <div className="md-nav-rail__footer">
          <NavItem item={{ path: "/help", icon: "help", label: "Hướng dẫn" }} current={path.startsWith("/help")} />
          <NavItem item={{ path: "/settings", icon: "settings", label: "Cài đặt" }} current={path.startsWith("/settings")} />
        </div>
      </nav>
      <div className="md-main">
        <header className={`md-top-app-bar${scrolled ? " md-top-app-bar--scrolled" : ""}`}>
          <h1 className="md-top-app-bar__title">{title}</h1>
          <div className="md-top-app-bar__actions">
            <md-icon-button aria-label="Đổi giao diện sáng/tối" onClick={() => {
              const next = cycleTheme();
              setTheme(next);
              window.md?.snackbar(THEME_TEXT[next]);
            }}><md-icon>{THEME_ICON[theme]}</md-icon></md-icon-button>
          </div>
        </header>
        <main className={`md-content${layout !== "page" ? ` md-content--${layout}` : ""}`}>
          {app.readonly ? <div className="md-banner md-banner--error" role="alert">
            <md-icon>lock</md-icon><div className="md-banner__text">{app.reason}</div>
            <Link to="/settings"><md-text-button>Sao lưu</md-text-button></Link>
          </div> : null}
          <Boundary path={path} addon={module?.addon}>
            <Suspense fallback={<div className="md-empty"><md-circular-progress indeterminate></md-circular-progress></div>}>
              <Page key={module?.key || path} module={module} subpath={subpath} api={api} />
            </Suspense>
          </Boundary>
        </main>
      </div>
    </div>
  </AppContext.Provider>;
}

export { NotFound };
