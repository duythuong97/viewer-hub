import React, { useEffect, useState } from "react";
import { businessApi } from "./api.js";
import { Button, Empty, ErrorBanner, Loading, Select, TextField } from "../../md/react.jsx";
import { Kind, ProgressBar, RichText, Status } from "./common.jsx";
import { partCounts } from "./lib/text.js";

export default function FeaturePage({ itemId, tree, onTree, onOpen, onExport, onImport, notify }) {
  const [item, setItem] = useState(null);
  const [error, setError] = useState("");
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState({ name: "", description: "" });
  const [parent, setParent] = useState("");
  const entry = findEntry(tree, itemId);

  // Only a different item closes the editor; a tree refresh (export, rename elsewhere) keeps unsaved text.
  useEffect(() => { setEditing(false); setItem(null); }, [itemId]);
  useEffect(() => {
    setError("");
    if (!itemId || entry) { setItem(null); return undefined; }
    let live = true;
    businessApi.item(itemId).then((body) => { if (live) setItem(body); }).catch((reason) => { if (live) setError(reason.message); });
    return () => { live = false; };
  }, [itemId, tree]); // eslint-disable-line react-hooks/exhaustive-deps

  if (!itemId) return <Welcome tree={tree} onOpen={onOpen} />;
  if (entry) return <EntryPage entry={entry} tree={tree} parent={parent} setParent={setParent} onTree={onTree} onOpen={onOpen} notify={notify} />;
  if (error) return <div className="cm-page"><ErrorBanner>{error}</ErrorBanner></div>;
  if (!item) return <Loading />;

  const counts = partCounts(item.parts || []);
  async function save(body, message) {
    try {
      const savedId = item.id;
      const result = await businessApi.updateItem(savedId, body);
      onTree(result.tree);
      if (result.item && result.item.id === savedId) setItem(result.item);
      setEditing(false);
      notify(message);
    } catch (reason) {
      notify(reason.message);
    }
  }

  const startEdit = () => { setDraft({ name: item.name, description: item.description || "" }); setEditing(true); };
  return <article className="cm-page">
    <header className="cm-page__head cm-page__head--actions">
      <div className="cm-page__title">
        <Kind icon={item.kind === "menu" ? "menu" : item.batch ? "schedule" : "web_asset"}>
          {item.kind === "menu" ? "Menu" : item.batch ? "Tính năng · chạy nền" : "Tính năng"}</Kind>
        <h1>{item.name}</h1>
        {item.path?.length > 1 ? <div className="md-muted">{item.path.slice(0, -1).map((step) => step.name).join(" / ")}</div> : null}
        {!editing ? <div className="cm-page__status"><Status status={item.status} by={item.reviewed_by} /></div> : null}
      </div>
      {!editing ? <div className="cm-page__actions">
        <Button icon="edit" onClick={startEdit}>Sửa</Button>
        {item.kind === "feature" ? <>
          <Button variant="outlined" icon="upload" onClick={() => onImport(item.id)}>Nhập kết quả AI</Button>
          <Button variant="filled" icon="auto_awesome" onClick={() => onExport(item.id)}>Xuất cho AI</Button>
        </> : null}
      </div> : null}
    </header>

    {editing ? <div className="cm-edit">
      <TextField label="Tên" value={draft.name} onChange={(name) => setDraft({ ...draft, name })} />
      <TextField label="Mô tả" type="textarea" rows={6} value={draft.description} onChange={(description) => setDraft({ ...draft, description })}
        supportingText="Đổi tên chỉ đổi phần hiển thị. Route và node gốc giữ nguyên." />
      <div className="cm-edit__foot"><span /><span className="md-row"><Button onClick={() => setEditing(false)}>Huỷ</Button>
        <Button variant="filled" icon="save" onClick={() => save({ name: draft.name, description: draft.description }, "Đã lưu")}>Lưu</Button></span></div>
    </div> : <>
      {item.description ? <RichText text={item.description} /> : <p className="md-muted">{item.kind === "feature" ? "Chưa có tổng quan. Bấm Xuất cho AI để AI viết tên và tổng quan cùng tài liệu các luồng, hoặc bấm Sửa để tự viết." : "Chưa có mô tả. Bấm Sửa để viết."}</p>}
    </>}

    {item.kind !== "menu" || !item.unsorted ? <div className="cm-stats">
      <div><b>{item.flow_count}</b><span>luồng</span></div>
      <div><b>{counts.total - counts.none}/{counts.total}</b><span>phần đã viết</span></div>
    </div> : null}

    {item.kind === "feature" ? <>
      <dl className="cm-entry">
        <div><dt>{item.batch ? "Jobnet" : "Route"}</dt><dd><code>{item.route}</code></dd></div>
        <div><dt>Điểm vào</dt><dd><code>{item.entry?.name}</code></dd></div>
        {item.apis?.length ? <div><dt>API</dt><dd>{item.apis.map((api) => <code key={api}>{api}</code>)}</dd></div> : null}
        {item.writes?.length ? <div><dt>Ghi bảng</dt><dd>{item.writes.map((name) => <code key={name}>{name}</code>)}</dd></div> : null}
        {item.reads?.length ? <div><dt>Đọc bảng</dt><dd>{item.reads.map((name) => <code key={name}>{name}</code>)}</dd></div> : null}
      </dl>
      <p className="md-muted cm-small cm-ai-note"><md-icon>auto_awesome</md-icon>
        <span>Xuất cho AI: node, cạnh, thứ tự gọi và đoạn code của tính năng này ({item.node_count} node) trong một file; AI viết tài liệu các luồng rồi tên và tổng quan tính năng, xong thì nhập lại ngay trong cùng hộp thoại.
          {item.last_export ? ` Lần xuất gần nhất: ${item.last_export.export_id} · ${item.last_export.created_at}.` : ""}</span></p>
      <section className="cm-list">
        <span className="cm-label">Luồng nghiệp vụ</span>
        {(item.children || []).map((flow) => <button key={flow.id} type="button" className="cm-card" onClick={() => onOpen(flow)}>
          <span className="cm-card__h"><b>{flow.name}</b>{flow.has_doc ? <ProgressBar parts={flow.parts} /> : <span className="cm-nodoc">chưa viết</span>}</span>
          {flow.summary ? <p>{flow.summary}</p> : null}
          <span className="cm-card__meta">{flow.has_doc ? `${partCounts(flow.parts).person}/${flow.parts.length} phần do người viết` : "Chưa có tài liệu · các bước đã được tách từ graph"}</span>
        </button>)}
      </section>
    </> : null}

    {item.kind === "menu" ? <section className="cm-list">
      <span className="cm-label">{item.unsorted ? "Entry point" : "Tính năng"}</span>
      {(item.children || []).map((child) => <button key={child.id} type="button" className="cm-card" onClick={() => onOpen(child)}>
        <span className="cm-card__h"><b className={child.kind === "entry" ? "cm-mono" : ""}>{child.name}</b>{child.parts?.length ? <ProgressBar parts={child.parts} /> : null}</span>
        <span className="cm-card__meta">{child.route ? <code>{child.route}</code> : null}{child.kind === "feature" ? <span>{child.flow_count} luồng</span> : <span>{child.node_type}</span>}</span>
      </button>)}
    </section> : null}
  </article>;
}

function findEntry(tree, id) {
  const unsorted = (tree?.menus || []).find((menu) => menu.unsorted);
  return unsorted?.children?.find((child) => child.id === id) || null;
}

function EntryPage({ entry, tree, parent, setParent, onTree, onOpen, notify }) {
  // Features at any depth (system > group > section > feature), labelled with their menu path.
  const collect = (items, path) => items.flatMap((item) => (item.kind === "feature" ? [{ ...item, menu: path.join(" / ") }]
    : item.kind === "menu" && !item.unsorted ? collect(item.children || [], [...path, item.name]) : []));
  const features = collect(tree?.menus || [], []);
  const target = parent || features[0]?.id || "";
  async function assign() {
    try {
      const result = await businessApi.updateItem(entry.id, { parent_id: target });
      onTree(result.tree);
      notify("Đã gán vào tính năng");
      const feature = features.find((child) => child.id === target);
      if (feature) onOpen(feature);
    } catch (reason) {
      notify(reason.message);
    }
  }
  return <article className="cm-page">
    <header className="cm-page__head">
      <Kind icon="power">Entry point chưa gán</Kind>
      <h1 className="cm-mono">{entry.name}</h1>
      <div className="md-muted">{entry.node_type} · {entry.node_id}</div>
    </header>
    <p className="cm-prose">Extractor tìm thấy entry point này nhưng không tính năng nào gọi tới nó, nên nó chưa có tài liệu. Gán nó vào một tính năng để AI viết luồng của nó cùng tính năng đó.</p>
    <Select label="Gán vào tính năng" value={target} onChange={setParent} className="cm-wide-field"
      options={features.map((feature) => [feature.id, `${feature.menu} / ${feature.name}`])} />
    <div className="md-row"><Button variant="filled" icon="link" disabled={!target} onClick={assign}>Gán</Button></div>
  </article>;
}

function Welcome({ tree, onOpen }) {
  const menus = (tree?.menus || []).filter((menu) => !menu.unsorted);
  return <article className="cm-page">
    <header className="cm-page__head">
      <h1>Hiểu hệ thống theo từng tính năng</h1>
      <p className="cm-lead">Mỗi menu là một nhóm tính năng, mỗi tính năng có các luồng nghiệp vụ. Tài liệu do AI viết từ graph, có trích dẫn tới từng node; bạn đọc và sửa khi cần, phần bạn sửa AI không viết đè. Chọn một mục ở menu trái hoặc tìm ở ô phía trên.</p>
    </header>
    <section className="cm-list">
      <span className="cm-label">Menu</span>
      {menus.map((menu) => <button key={menu.id} type="button" className="cm-card" onClick={() => onOpen(menu)}>
        <span className="cm-card__h"><b>{menu.name}</b><ProgressBar parts={menu.parts || []} /></span>
        <span className="cm-card__meta"><span>{(menu.children || []).length} tính năng</span><span>{menu.flow_count} luồng</span></span>
      </button>)}
      {!menus.length ? <Empty icon="account_tree" title="Chưa có màn hình hay jobnet">Graph chưa có màn hình (SCREEN) hay jobnet nào. Hãy chạy extract với source Angular hoặc jobnet.csv.</Empty> : null}
    </section>
  </article>;
}
