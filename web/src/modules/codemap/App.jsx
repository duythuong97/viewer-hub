import React, { useCallback, useEffect, useState } from "react";
import { businessApi, currentUser, setCurrentUser } from "./api.js";
import { config, notify } from "./config.js";
import { AiDialog } from "./AiDialogs.jsx";
import ErdMoved from "./ErdMoved.jsx";
import FeaturePage from "./FeaturePage.jsx";
import FlowView from "./FlowView.jsx";
import { KbStatusPage, KnowledgePage } from "./KnowledgePages.jsx";
import { ErrorBanner, IconButton, Loading, Select, TextField } from "../../md/react.jsx";
import NavTree from "./NavTree.jsx";
import NodePage from "./NodePage.jsx";
import SearchBox from "./SearchBox.jsx";
import SnippetDialog from "./SnippetDialog.jsx";
import { parseRoute, routeHash } from "./lib/text.js";

function findItem(tree, id) {
  const stack = [...(tree?.menus || [])];
  while (stack.length) {
    const item = stack.pop();
    if (item.id === id) return item;
    stack.push(...(item.children || []));
  }
  return null;
}

// The name recorded on edits, answers and decisions (sent as X-Code-Map-User).
function UserName() {
  const [name, setName] = useState(currentUser);
  return <TextField className="cm-user" label="Tên của bạn" leadingIcon="person" value={name}
    onChange={(value) => { setName(value.slice(0, 100)); setCurrentUser(value.trim().slice(0, 100)); }} />;
}

function PackPicker() {
  if ((config.packs || []).length < 2) return null;
  return <Select className="cm-pack" label="Pack" value={config.pack}
    options={config.packs.map((pack) => [pack.id, pack.version ? `${pack.title} · ${pack.version}` : pack.title])}
    onChange={(id) => { if (id && id !== config.pack) window.location.search = `?pack=${encodeURIComponent(id)}`; }} />;
}

function TopLink({ href, icon, label, on, count }) {
  return <a className={`cm-toplink${on ? " is-on" : ""}`} href={href} aria-current={on ? "page" : undefined} title={label}>
    <md-icon>{icon}</md-icon><span className="cm-toplink__label">{label}</span>{count ? <span className="md-badge md-badge--error">{count}</span> : null}
  </a>;
}

export default function App() {
  const [route, setRoute] = useState(() => parseRoute(window.location.hash));
  const [tree, setTree] = useState(null);
  const [error, setError] = useState("");
  const [collapsed, setCollapsed] = useState(false);
  const [drawer, setDrawer] = useState(false);
  const [dialog, setDialog] = useState(null);
  const [refresh, setRefresh] = useState(0);

  useEffect(() => {
    const onHash = () => setRoute(parseRoute(window.location.hash));
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);

  useEffect(() => {
    businessApi.tree().then(setTree).catch((reason) => setError(reason.message));
  }, []);

  const go = useCallback((view, id) => {
    window.location.hash = routeHash(view, id);
    setDrawer(false);
  }, []);

  const openItem = useCallback((item) => {
    if (!item) return;
    go(item.kind === "flow" ? "flow" : "feature", item.id);
  }, [go]);

  function pickSearch(hit) {
    if (hit.group === "node") { go("node", hit.id); return; }
    if (hit.kind === "flow" || hit.kind === "step" || hit.kind === "rule") go("flow", hit.id);
    else go("feature", hit.id);
  }

  function toggleNav() {
    if (window.matchMedia("(max-width: 1080px)").matches) setDrawer(!drawer);
    else setCollapsed(!collapsed);
  }

  const onTree = useCallback((next) => { if (next) setTree(next); }, []);
  const featureOf = (id) => findItem(tree, id);
  const exportDialog = (featureId) => setDialog({ type: "export", featureId });
  const importDialog = (featureId) => setDialog({ type: "import", featureId });
  const snippet = (path, targetId) => setDialog({ type: "snippet", path, targetId });
  const openNode = (id) => go("node", id);

  const selectedId = route.id;
  let page;
  if (error) page = <div className="cm-page"><ErrorBanner>{error}</ErrorBanner></div>;
  else if (!tree) page = <div className="cm-page" style={{ padding: 24 }}><Loading>Đang nạp cây tính năng…</Loading></div>;
  else if (route.view === "knowledge") page = <div className="cm-scroll"><KnowledgePage onOpenNode={openNode} notify={notify} /></div>;
  else if (route.view === "erd") page = <ErdMoved params={route.params || {}} />;
  else if (route.view === "kb") page = <div className="cm-scroll"><KbStatusPage onOpenKnowledge={() => go("knowledge")} mcpUrl={config.mcpUrl} notify={notify} /></div>;
  else if (route.view === "flow" && selectedId) page = <FlowView key={`${selectedId}:${refresh}`} flowId={selectedId} onTree={onTree} onOpenItem={openItem}
    onOpenNode={openNode} onExport={exportDialog} onImport={importDialog} onSnippet={snippet} notify={notify} />;
  else if (route.view === "node" && selectedId) page = <NodePage key={selectedId} nodeId={selectedId} onOpenItem={openItem} onOpenNode={openNode} onSnippet={snippet} notify={notify} />;
  else page = <div className="cm-scroll"><FeaturePage key={selectedId || "home"} itemId={selectedId} tree={tree} onTree={onTree} onOpen={openItem}
    onExport={exportDialog} onImport={importDialog} onOpenNode={openNode} notify={notify} /></div>;

  return <div className="cm-app">
    <div className="cm-toolbar">
      <IconButton icon={collapsed ? "menu" : "menu_open"} label="Ẩn hoặc hiện menu tính năng" onClick={toggleNav} />
      <a className="cm-home" href="#/" title="Trang đầu code map"><md-icon>account_tree</md-icon></a>
      <SearchBox onPick={pickSearch} />
      <nav className="cm-toolbar__links" aria-label="Trang của code map">
        {config.erdAddon ? <TopLink href={`${config.erdAddon}/?pack=${encodeURIComponent(config.pack)}`} icon="schema" label="ERD" /> : null}
        <TopLink href="#/knowledge" icon="balance" label="Quy tắc" on={route.view === "knowledge"} />
        <TopLink href="#/kb" icon="monitoring" label="KB" on={route.view === "kb"} />
      </nav>
      <PackPicker />
      <UserName />
    </div>
    <div className={`cm-body${collapsed ? " is-collapsed" : ""}${drawer ? " is-drawer" : ""}`}>
      {tree ? <NavTree tree={tree} selectedId={selectedId} onSelect={openItem} />
        : <nav className="cm-nav">{error ? <p className="md-muted cm-pad">{error}</p> : <Loading>Đang tải cây tính năng…</Loading>}</nav>}
      {drawer ? <div className="cm-scrim" onClick={() => setDrawer(false)} /> : null}
      <main className="cm-main">{page}</main>
    </div>
    {dialog?.type === "export" || dialog?.type === "import" ? <AiDialog key={dialog.featureId} featureId={dialog.featureId}
      featureName={featureOf(dialog.featureId)?.name || ""} startStep={dialog.type === "export" ? 0 : 1} notify={notify}
      onExported={() => businessApi.tree().then(setTree).catch(() => {})}
      onImported={(next) => { onTree(next); setRefresh((value) => value + 1); }} onClose={() => setDialog(null)} /> : null}
    {dialog?.type === "snippet" ? <SnippetDialog path={dialog.path} targetId={dialog.targetId} onClose={() => setDialog(null)} /> : null}
  </div>;
}
