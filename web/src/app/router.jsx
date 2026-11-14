// Tiny history router (no dependency): the URL path picks the page; links inside the app change it without a reload.
import React, { createContext, useContext, useEffect, useState } from "react";

const RouterContext = createContext({ path: "/", search: "", navigate: () => {} });

function current() {
  return { path: window.location.pathname, search: window.location.search, hash: window.location.hash };
}

export function Router({ children }) {
  const [location, setLocation] = useState(current);
  useEffect(() => {
    const onPop = () => setLocation(current());
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, []);
  const navigate = (to, { replace = false } = {}) => {
    const url = new URL(to, window.location.href);
    if (url.origin !== window.location.origin) {
      window.location.assign(url.href);
      return;
    }
    window.history[replace ? "replaceState" : "pushState"]({}, "", url.pathname + url.search + url.hash);
    setLocation(current());
    if (!url.hash) window.scrollTo(0, 0);
  };
  return <RouterContext.Provider value={{ ...location, navigate }}>{children}</RouterContext.Provider>;
}

export const useRouter = () => useContext(RouterContext);

/** Query string of the current URL as an object; setQuery replaces it (keeps the path). */
export function useQuery() {
  const { path, search, navigate } = useRouter();
  const query = Object.fromEntries(new URLSearchParams(search));
  const setQuery = (next, options) => {
    const params = new URLSearchParams(Object.entries(next).filter(([, v]) => v !== undefined && v !== null && v !== ""));
    const text = params.toString();
    navigate(path + (text ? `?${text}` : ""), options);
  };
  return [query, setQuery];
}

/** <a> that navigates inside the app; external, new-tab and modified clicks behave as a normal link. */
export function Link({ to, children, className, ...rest }) {
  const { navigate } = useRouter();
  const onClick = (event) => {
    if (event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    if (rest.target && rest.target !== "_self") return;
    event.preventDefault();
    navigate(to);
  };
  return <a href={to} className={className} onClick={onClick} {...rest}>{children}</a>;
}
