// What every page can read: the app config from GET /api/app, and a way to set the top app bar title.
import { createContext, useContext, useEffect } from "react";

export const AppContext = createContext({ app: null, setTitle: () => {}, setLayout: () => {}, reload: () => {} });

export const useApp = () => useContext(AppContext);

/** Sets the top app bar title (and the tab title) while the page is shown. */
export function useTitle(title) {
  const { setTitle } = useApp();
  useEffect(() => {
    setTitle(title);
    document.title = title && title !== "Viewer Hub" ? `${title} · Viewer Hub` : "Viewer Hub";
  }, [title, setTitle]);
}

/** Page width while the page is shown: "page" (default), "wide" (tables, results) or "full" (no padding, fills the
 *  window: code map). */
export function useLayout(layout) {
  const { setLayout } = useApp();
  useEffect(() => {
    setLayout(layout);
    return () => setLayout("page");
  }, [layout, setLayout]);
}
