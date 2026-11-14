// Addon SDK v1: react-dom of the Hub (portals); the Hub owns the root, addons never call createRoot.
import * as ReactDOM from "react-dom";

export default ReactDOM;
export const { createPortal, flushSync } = ReactDOM;
