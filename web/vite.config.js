// Build-time only. Output: viewer_hub/static/dist/ with stable entry names:
//   md.js/.css   Material 3 design system (also used by generated docs sites)
//   app.js/.css  the single-page app (templates/app.html); module pages are lazy chunks of it
//   sdk/*.js     the addon SDK (docs/addons.md §5.3): react, jsx-runtime, react-dom, md (components), ui (page kit),
//                mermaid (diagrams; Mermaid itself is a lazy chunk), flow (React Flow + layoutGraph in a Worker).
//                Addon pages (their own ui.js, built by the SDK: viewer_hub/addons/kit/sdk/build.mjs) import these by URL, so the Hub and
//                every addon share one React and one set of Material elements. app.js shares the same chunks.
import { resolve } from 'node:path';
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

const entries = {
  md: 'src/md/index.js',
  app: 'src/app/main.jsx',
  'sdk/react': 'src/sdk/react.js',
  'sdk/jsx-runtime': 'src/sdk/jsx-runtime.js',
  'sdk/react-dom': 'src/sdk/react-dom.js',
  'sdk/md': 'src/sdk/md.js',
  'sdk/ui': 'src/sdk/ui.js',
  'sdk/mermaid': 'src/sdk/mermaid.js',
  'sdk/flow': 'src/sdk/flow.js',
};
const input = Object.fromEntries(Object.entries(entries).map(([name, file]) => [name, resolve(import.meta.dirname, file)]));

export default defineConfig({
  base: '/static/dist/',
  plugins: [react()],
  worker: { format: 'es' },
  build: {
    outDir: resolve(import.meta.dirname, '../viewer_hub/static/dist'),
    emptyOutDir: true,
    sourcemap: false,
    // Everything ships in the release; nothing is fetched from a CDN at runtime.
    assetsInlineLimit: 0,
    rollupOptions: {
      input,
      // Keep entry exports exactly: sdk/*.js is a public API imported by addon pages.
      preserveEntrySignatures: 'strict',
      output: {
        entryFileNames: '[name].js',
        chunkFileNames: 'chunks/[name]-[hash].js',
        // Entry CSS keeps a stable name (app.html links it); lazy page CSS is hashed and loaded with its chunk.
        assetFileNames: (asset) =>
          asset.names?.some((n) => ['md.css', 'app.css'].includes(n)) ? '[name][extname]' : 'assets/[name]-[hash][extname]',
      },
    },
  },
});
