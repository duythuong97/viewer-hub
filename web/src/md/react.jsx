// Thin React wrappers over the @material/web custom elements that /static/dist/md.js registers.
// Events are attached with addEventListener (the elements re-dispatch native events from their shadow
// DOM) and values are set as properties after mount, so every element stays in sync with React state.
import React, { useEffect, useRef } from "react";

function useListener(ref, name, handler) {
  const saved = useRef(handler);
  saved.current = handler;
  useEffect(() => {
    const element = ref.current;
    if (!element) return undefined;
    const listener = (event) => saved.current?.(event);
    element.addEventListener(name, listener);
    return () => element.removeEventListener(name, listener);
  }, [ref, name]);
}

export function Icon({ children, filled, className = "", size }) {
  return <md-icon class={className} filled={filled ? true : undefined} style={size ? { "--md-icon-size": `${size}px` } : undefined}>{children}</md-icon>;
}

// variant: filled | tonal | outlined | text; danger: error colours (delete, stop, wide permissions)
export function Button({ variant = "text", icon, children, onClick, disabled, title, type = "button", className = "", trailingIcon, danger }) {
  const Tag = { filled: "md-filled-button", tonal: "md-filled-tonal-button", outlined: "md-outlined-button", text: "md-text-button" }[variant] || "md-text-button";
  return <Tag class={`${className}${danger ? " md-button--danger" : ""}`} type={type} disabled={disabled || undefined} title={title} onClick={disabled ? undefined : onClick}
    trailing-icon={trailingIcon ? true : undefined}>
    {icon ? <md-icon slot="icon">{icon}</md-icon> : null}
    {children}
  </Tag>;
}

export function IconButton({ icon, label, onClick, disabled, selected, toggle, className = "", variant, danger }) {
  const Tag = variant === "tonal" ? "md-filled-tonal-icon-button" : variant === "outlined" ? "md-outlined-icon-button" : "md-icon-button";
  return <Tag class={`${className}${danger ? " md-button--danger" : ""}`} aria-label={label} title={label} disabled={disabled || undefined} toggle={toggle || undefined}
    selected={selected || undefined} onClick={onClick}>
    <md-icon>{icon}</md-icon>
  </Tag>;
}

// One-line or textarea field. `onChange(value)`.
export function TextField({ label, value, onChange, type = "text", rows, placeholder, supportingText, className = "", maxLength, inputRef, onKeyDown, leadingIcon, ariaLabel, readOnly, autoComplete }) {
  const ref = useRef(null);
  useEffect(() => { if (ref.current && ref.current.value !== (value ?? "")) ref.current.value = value ?? ""; }, [value]);
  useEffect(() => { if (inputRef) inputRef.current = ref.current; }, [inputRef]);
  useListener(ref, "input", (event) => onChange?.(event.target.value));
  useListener(ref, "keydown", (event) => onKeyDown?.(event));
  return <md-outlined-text-field ref={ref} class={className} label={label} type={type} rows={rows}
    placeholder={placeholder} supporting-text={supportingText} maxlength={maxLength} aria-label={ariaLabel || label}
    readonly={readOnly || undefined} autocomplete={autoComplete}>
    {leadingIcon ? <md-icon slot="leading-icon">{leadingIcon}</md-icon> : null}
  </md-outlined-text-field>;
}

// options: [[value, label]]. `onChange(value)`.
export function Select({ label, ariaLabel, value, onChange, options, className = "", disabled }) {
  const ref = useRef(null);
  const signature = options.map(([key, text]) => `${key}:${text}`).join("|");
  useEffect(() => {
    const element = ref.current;
    if (!element) return;
    const apply = () => { if (element.value !== value) element.value = value; };
    apply();
    // Options are slotted; the select reads them once it has rendered.
    Promise.resolve(element.updateComplete).then(() => requestAnimationFrame(apply));
  }, [value, signature]);
  useListener(ref, "change", (event) => onChange?.(event.target.value));
  return <md-outlined-select ref={ref} class={className} label={label} aria-label={ariaLabel || label} disabled={disabled || undefined}>
    {options.map(([key, text]) => <md-select-option key={key} value={key}><div slot="headline">{text}</div></md-select-option>)}
  </md-outlined-select>;
}

// M3 switch with a label. `onChange(selected)`.
export function Switch({ selected, onChange, children, title, disabled, label }) {
  const ref = useRef(null);
  useEffect(() => { if (ref.current) ref.current.selected = Boolean(selected); }, [selected]);
  useListener(ref, "change", (event) => onChange?.(event.target.selected));
  return <label className="md-label-switch" title={title}>
    <md-switch ref={ref} disabled={disabled || undefined} aria-label={label}></md-switch>{children}</label>;
}

export function Checkbox({ checked, onChange, label, supporting, disabled }) {
  const ref = useRef(null);
  useEffect(() => { if (ref.current) ref.current.checked = Boolean(checked); }, [checked]);
  useListener(ref, "change", (event) => onChange?.(event.target.checked));
  return <label className="cm-check">
    <md-checkbox ref={ref} touch-target="wrapper" disabled={disabled || undefined} />
    <span>{label}{supporting ? <small>{supporting}</small> : null}</span>
  </label>;
}

// M3 dialog. `onClose` runs when it closes (scrim, Escape or an action).
export function Dialog({ headline, icon, children, actions, onClose, wide, className = "" }) {
  const ref = useRef(null);
  useEffect(() => {
    const element = ref.current;
    if (element) element.open = true;
  }, []);
  useListener(ref, "closed", () => onClose?.());
  const close = () => { if (ref.current) ref.current.open = false; else onClose?.(); };
  return <md-dialog ref={ref} class={`cm-dialog${wide ? " cm-dialog--wide" : ""} ${className}`}>
    <div slot="headline" className="cm-dialog__headline">
      {icon ? <md-icon className="cm-dialog__icon">{icon}</md-icon> : null}<span>{headline}</span>
      <md-icon-button aria-label="Đóng" onClick={close}><md-icon>close</md-icon></md-icon-button></div>
    <div slot="content" className="cm-dialog__content">{children}</div>
    {actions ? <div slot="actions">{typeof actions === "function" ? actions(close) : actions}</div> : null}
  </md-dialog>;
}

// tabs: [[key, label, icon?]]
export function Tabs({ tabs, value, onChange, className = "" }) {
  const ref = useRef(null);
  const index = Math.max(0, tabs.findIndex(([key]) => key === value));
  useEffect(() => { if (ref.current && ref.current.activeTabIndex !== index) ref.current.activeTabIndex = index; }, [index]);
  useListener(ref, "change", (event) => {
    const next = tabs[event.target.activeTabIndex];
    if (next && next[0] !== value) onChange(next[0]);
  });
  return <md-tabs ref={ref} class={className}>
    {tabs.map(([key, label, icon]) => <md-primary-tab key={key} inline-icon={icon ? true : undefined}>
      {icon ? <md-icon slot="icon">{icon}</md-icon> : null}{label}</md-primary-tab>)}
  </md-tabs>;
}

// M3 segmented button (not shipped by @material/web): options [[key, label, icon?]].
export function Segmented({ options, value, onChange, label, dense }) {
  return <div className={`cm-seg${dense ? " cm-seg--dense" : ""}`} role="group" aria-label={label}>
    {options.map(([key, text, icon]) => {
      const selected = value === key;
      return <button key={key} type="button" aria-pressed={selected} className="cm-seg__btn" onClick={() => onChange(key)} title={typeof text === "string" ? text : undefined}>
        {selected ? <md-icon>check</md-icon> : icon ? <md-icon>{icon}</md-icon> : null}
        {text ? <span>{text}</span> : null}
      </button>;
    })}
  </div>;
}

export function Chip({ selected, onClick, children, title }) {
  const ref = useRef(null);
  useEffect(() => { if (ref.current) ref.current.selected = Boolean(selected); }, [selected]);
  return <md-filter-chip ref={ref} label={typeof children === "string" ? children : undefined} title={title}
    onClick={(event) => { event.preventDefault(); onClick?.(); }}>
    {typeof children === "string" ? null : children}
  </md-filter-chip>;
}

export function Progress() {
  return <md-linear-progress indeterminate class="cm-progress" />;
}

export function Loading({ children = "Đang tải…" }) {
  return <div className="cm-loading"><md-circular-progress indeterminate /><span>{children}</span></div>;
}

export function ErrorBanner({ children }) {
  return <div className="md-banner md-banner--error" role="alert"><md-icon>error</md-icon><div className="md-banner__text">{children}</div></div>;
}

export function Empty({ icon = "inbox", title, children }) {
  return <div className="md-empty cm-empty"><md-icon>{icon}</md-icon>{title ? <h2>{title}</h2> : null}{children ? <p>{children}</p> : null}</div>;
}

// Removable chip for an active filter (md-input-chip fires "remove").
export function InputChip({ label, onRemove }) {
  const ref = useRef(null);
  useListener(ref, "remove", (event) => { event.preventDefault(); onRemove?.(); });
  return <md-input-chip ref={ref} label={label} remove-only />;
}

// Shared filter UI (F-Search, code map, MCP Bridge…): [Bộ lọc · n] [active chips…] … summary, then the panel.
// filters: [{ key, label, value, options: [[value, label]], defaultValue }]; onApply(values).
export function FilterBar({ filters, onApply, summary, panelId }) {
  const [open, setOpen] = React.useState(false);
  const [draft, setDraft] = React.useState(() => Object.fromEntries(filters.map((filter) => [filter.key, filter.value])));
  const active = filters.filter((filter) => filter.value !== filter.defaultValue);
  const optionLabel = (filter) => filter.options.find(([value]) => value === filter.value)?.[1] || filter.value;
  function toggle() {
    if (!open) setDraft(Object.fromEntries(filters.map((filter) => [filter.key, filter.value])));
    setOpen(!open);
  }
  const reset = () => setDraft(Object.fromEntries(filters.map((filter) => [filter.key, filter.defaultValue])));
  return <>
    <div className="md-filter-bar">
      <md-outlined-button type="button" aria-controls={panelId} aria-expanded={open ? "true" : "false"} data-open={open ? "" : undefined} onClick={toggle}>
        <md-icon slot="icon">tune</md-icon>Bộ lọc{active.length ? ` · ${active.length}` : ""}
      </md-outlined-button>
      <md-chip-set class="md-filter-bar__chips">
        {active.map((filter) => <InputChip key={filter.key} label={`${filter.label}: ${optionLabel(filter)}`}
          onRemove={() => onApply({ ...Object.fromEntries(filters.map((item) => [item.key, item.value])), [filter.key]: filter.defaultValue })} />)}
      </md-chip-set>
      {summary ? <span className="md-filter-bar__summary">{summary}</span> : null}
    </div>
    {open ? <section className="md-filter-panel" id={panelId} aria-label="Bộ lọc">
      <div className="md-filter-panel__grid">
        {filters.map((filter) => <div key={filter.key} className="md-filter-panel__wide">
          <h3>{filter.label}</h3>
          <md-chip-set>{filter.options.map(([value, text]) => <Chip key={value} selected={draft[filter.key] === value}
            onClick={() => setDraft({ ...draft, [filter.key]: value })}>{text}</Chip>)}</md-chip-set>
        </div>)}
      </div>
      <div className="md-filter-panel__actions">
        <Button onClick={reset}>Đặt lại</Button>
        <Button variant="filled" onClick={() => { onApply(draft); setOpen(false); }}>Áp dụng</Button>
      </div>
    </section> : null}
  </>;
}
