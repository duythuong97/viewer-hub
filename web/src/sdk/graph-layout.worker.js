// Runs layoutGraph() off the page's thread (see flow.js): big graphs lay out without freezing the page.
import { layoutGraph } from "./graph-layout.js";

self.onmessage = (event) => {
  const { id, input, options } = event.data || {};
  try {
    self.postMessage({ id, result: layoutGraph(input, options) });
  } catch (err) {
    self.postMessage({ id, error: String(err?.message || err) });
  }
};
