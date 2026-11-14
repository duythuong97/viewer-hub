// Addon SDK v1: Mermaid of the Hub ("@vh/mermaid"), so an addon page draws diagrams without bundling Mermaid (and its
// d3 / DOMPurify, which the install scan would refuse in an addon's ui/). Locked to the safe settings: strict security
// (labels sanitised, no click handlers / scripts in the SVG), plain SVG text (so a PNG export works). Mermaid itself
// loads on the first render only. Renders run one after another: mermaid.initialize() is global.
let loading = null;
let queue = Promise.resolve();
let counter = 0;

function load() {
  if (!loading) loading = import("mermaid").then((m) => m.default);
  return loading;
}

/** True when the Hub page is dark (follows the Hub theme). */
export function pageIsDark() {
  const theme = document.documentElement.dataset.theme;
  if (theme === "dark" || theme === "light") return theme === "dark";
  const m = (getComputedStyle(document.body).backgroundColor || "").match(/\d+(\.\d+)?/g);
  if (!m || m.length < 3) return window.matchMedia?.("(prefers-color-scheme: dark)").matches || false;
  const [r, g, b] = m.map(Number);
  return (0.2126 * r + 0.7152 * g + 0.0722 * b) / 255 < 0.5;
}

function setup(mermaid, theme) {
  mermaid.initialize({
    startOnLoad: false,
    securityLevel: "strict",
    theme: theme === "export" || (theme === "page" && !pageIsDark()) ? "default" : theme === "page" ? "dark" : theme,
    htmlLabels: false,
    flowchart: { htmlLabels: false },
    fontFamily: "inherit",
  });
}

function serial(job) {
  const run = queue.then(job);
  queue = run.catch(() => {});
  return run;
}

/** Throws Error(readable syntax message) when `text` is not valid Mermaid; else the diagram type. */
export function parse(text) {
  return serial(async () => {
    const mermaid = await load();
    setup(mermaid, "page");
    const result = await mermaid.parse(text);
    return result?.diagramType ?? "";
  });
}

/**
 * Mermaid text → { svg }: an SVG string, sanitised by Mermaid's strict mode. Show it with svgElement(svg) (a node to
 * append; innerHTML is refused in addon pages). theme: "page" (follows the Hub, default), "export" (light, for
 * files), or a Mermaid theme name.
 */
export function render(text, { theme = "page" } = {}) {
  return serial(async () => {
    const mermaid = await load();
    setup(mermaid, theme);
    await mermaid.parse(text);
    const id = `vh-mermaid-${++counter}`;
    try {
      const { svg } = await mermaid.render(id, text);
      return { svg };
    } finally {
      document.getElementById(id)?.remove();
      document.getElementById(`d${id}`)?.remove();
    }
  });
}

/** The SVG string of render() as an <svg> element (parsed as XML, never as HTML). */
export function svgElement(svg) {
  const doc = new DOMParser().parseFromString(svg, "image/svg+xml");
  const root = doc.documentElement;
  if (root.nodeName !== "svg") throw new Error("SVG không hợp lệ");
  return document.importNode(root, true);
}

export default { render, parse, svgElement, pageIsDark };
