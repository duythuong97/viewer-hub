// Which page shows for a URL. Builtin module pages are found by folder (web/src/modules/<key>/index.jsx, key = the
// backend module's key, app/modules.py). An installed addon's page is its own built file the server names in
// /api/app (scripts, styles), shown inside the Hub's frame (pages/AddonFrame.jsx: header, run / stop, log), or the
// Hub's own addon page (pages/Addon.jsx) when it has none. Core pages: ./pages/.
import { lazy } from "react";
import { framed } from "./pages/AddonFrame.jsx";

const MODULES = import.meta.glob("../modules/*/index.jsx");
const CORE = {
  "/": lazy(() => import("./pages/Home.jsx")),
  "/settings": lazy(() => import("./pages/Settings.jsx")),
  "/help": lazy(() => import("./pages/Help.jsx")),
  "/premium": lazy(() => import("./pages/Premium.jsx")),
};
export const NotFound = lazy(() => import("./pages/NotFound.jsx"));
const AddonPage = lazy(() => import("./pages/Addon.jsx"));

const cache = new Map();

/** Adds an addon's stylesheet once (it stays for the session, like the Hub's own lazy page CSS). */
function addStyle(href) {
  if (!href || document.querySelector(`link[data-addon-style="${CSS.escape(href)}"]`)) return;
  const link = document.createElement("link");
  link.rel = "stylesheet";
  link.href = href;
  link.dataset.addonStyle = href;
  document.head.append(link);
}

function moduleLoader(item, app) {
  const local = MODULES[`../modules/${item.key}/index.jsx`];
  if (local && !item.addon) return local;
  const script = app.scripts?.[item.key];
  if (script) {
    return () => {
      addStyle(app.styles?.[item.key]);
      return import(/* @vite-ignore */ script);
    };
  }
  return item.addon ? "auto" : null;
}

/** {Page, module, subpath} for a path; Page is a lazy component. */
export function resolve(path, app) {
  const trimmed = path.length > 1 ? path.replace(/\/+$/, "") : path;
  if (CORE[trimmed]) return { Page: CORE[trimmed], module: null, subpath: "" };
  const module = app.nav.find((item) => item.module && (trimmed === item.path || trimmed.startsWith(item.path + "/")));
  if (module) {
    const load = moduleLoader(module, app);
    if (load) {
      const key = `${module.key}:${app.scripts?.[module.key] || ""}`;
      if (!cache.has(key)) cache.set(key, load === "auto" ? AddonPage : module.addon ? framed(lazy(load)) : lazy(load));
      return { Page: cache.get(key), module, subpath: trimmed.slice(module.path.length) || "/" };
    }
  }
  return { Page: NotFound, module: null, subpath: "" };
}
