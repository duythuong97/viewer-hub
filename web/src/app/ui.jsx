// Page building blocks shared by every page (GUIDELINE §4): page header, search bar, link cards, list rows.
import React, { useCallback, useEffect, useRef, useState } from "react";
import { Button, Dialog } from "../md/react.jsx";
import { useRouter } from "./router.jsx";

// One page header (GUIDELINE §4.7): title + one line on the left, the page's actions on the right.
// title "" on a section's own page: the top app bar already names it.
export function PageHeader({ title = "", subtitle = "", children }) {
  return <section className={`md-page-header${title ? "" : " md-page-header--plain"}`}>
    <div className="md-page-header__text">
      {title ? <h1>{title}</h1> : null}
      {subtitle ? <p>{subtitle}</p> : null}
    </div>
    {children ? <div className="md-page-header__actions">{children}</div> : null}
  </section>;
}

// Search bar (GUIDELINE §4.2): Enter or the button submits; × clears (and submits an empty search).
export function SearchBar({ value, onSubmit, placeholder = "Tìm kiếm", autoFocus }) {
  const [text, setText] = useState(value ?? "");
  const ref = useRef(null);
  useEffect(() => setText(value ?? ""), [value]);
  const submit = (next = text) => onSubmit(next.trim());
  return <form className="md-search-bar" role="search" onSubmit={(event) => { event.preventDefault(); submit(); }}>
    <md-icon>search</md-icon>
    <input ref={ref} type="search" value={text} placeholder={placeholder} aria-label={placeholder} autoComplete="off"
      spellCheck="false" autoFocus={autoFocus} onChange={(event) => setText(event.target.value)} />
    {text ? <md-icon-button type="button" class="md-search-bar__clear" aria-label="Xoá nội dung tìm"
      onClick={() => { setText(""); ref.current?.focus(); submit(""); }}><md-icon>close</md-icon></md-icon-button> : null}
    <md-filled-icon-button class="md-search-bar__submit" aria-label="Tìm" title="Tìm (Enter)" onClick={() => submit()}>
      <md-icon>search</md-icon></md-filled-icon-button>
  </form>;
}

// Material button that navigates inside the app.
export function LinkButton({ to, icon, children, variant = "tonal" }) {
  const { navigate } = useRouter();
  const Tag = { filled: "md-filled-button", tonal: "md-filled-tonal-button", outlined: "md-outlined-button", text: "md-text-button" }[variant];
  return <Tag onClick={() => navigate(to)}>{icon ? <md-icon slot="icon">{icon}</md-icon> : null}{children}</Tag>;
}

// Home page card linking to a section.
export function LinkCard({ to, icon, title, children }) {
  const { navigate } = useRouter();
  return <a className="md-card md-card--link" href={to} onClick={(event) => {
    if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey) return;
    event.preventDefault();
    navigate(to);
  }}>
    <md-elevation></md-elevation><md-ripple></md-ripple>
    <div className="md-card__body">
      <span className="md-card__icon"><md-icon>{icon}</md-icon></span>
      <h2 className="md-card__title">{title}</h2>
      {children ? <p className="md-card__subtitle">{children}</p> : null}
    </div>
  </a>;
}

export function ListItem({ icon, headline, supporting, children }) {
  return <li className="md-list-item">
    {icon ? <md-icon class="md-list-item__leading">{icon}</md-icon> : null}
    <div className="md-list-item__content">
      <p className="md-list-item__headline">{headline}</p>
      {supporting ? <span className="md-list-item__supporting">{supporting}</span> : null}
    </div>
    {children}
  </li>;
}

export function Badge({ tone, icon, children }) {
  return <span className={`md-badge${tone ? ` md-badge--${tone}` : ""}`}>
    {icon ? <md-icon style={{ "--md-icon-size": "16px" }}>{icon}</md-icon> : null}{children}</span>;
}

/**
 * Asks before a dangerous action (GUIDELINE §4.2): delete, stop, giving wide permissions. Returns [confirm, dialog]:
 * render `dialog` once in the page, then `if (await confirm({ title, text, confirm: "Xoá" })) …`.
 * Options: title, text (or body: a node), confirm (button label, default "Đồng ý"), icon, danger (default true: red
 * button and icon; false for a plain question).
 */
export function useConfirm() {
  const [asked, setAsked] = useState(null);
  const answer = useRef(false);
  const confirm = useCallback((options) => new Promise((resolve) => {
    answer.current = false;
    setAsked({ ...options, resolve });
  }), []);
  const danger = asked?.danger !== false;
  const dialog = asked ? <Dialog icon={asked.icon || (danger ? "warning" : "help")} headline={asked.title}
    className={danger ? "md-dialog--danger" : ""}
    onClose={() => { asked.resolve(answer.current); setAsked(null); }}
    actions={(close) => <>
      <Button onClick={close}>{asked.cancel || "Huỷ"}</Button>
      <Button variant="filled" danger={danger} icon={asked.confirmIcon}
        onClick={() => { answer.current = true; close(); }}>{asked.confirm || "Đồng ý"}</Button>
    </>}>
    {asked.text ? <p>{asked.text}</p> : null}{asked.body || null}
  </Dialog> : null;
  return [confirm, dialog];
}

/** Runs an async action with a busy flag; errors go to the snackbar. Returns [run, busy]. */
export function useAction() {
  const [busy, setBusy] = useState(false);
  const run = async (action, done) => {
    setBusy(true);
    try {
      const result = await action();
      if (done) window.md?.snackbar(typeof done === "function" ? done(result) : done);
      return result;
    } catch (error) {
      window.md?.snackbar(error.message || String(error));
      return undefined;
    } finally {
      setBusy(false);
    }
  };
  return [run, busy];
}

/** Loads JSON once per `deps`; returns {data, error, loading, reload}. */
export function useLoad(load, deps = []) {
  const [state, setState] = useState({ data: null, error: null, loading: true });
  const [tick, setTick] = useState(0);
  useEffect(() => {
    let alive = true;
    setState((previous) => ({ ...previous, loading: true, error: null }));
    load().then((data) => alive && setState({ data, error: null, loading: false }),
      (error) => alive && setState({ data: null, error, loading: false }));
    return () => { alive = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, tick]);
  return { ...state, reload: () => setTick((n) => n + 1) };
}

