// Business notes on one node (kn.graph_knowledge): read, add, edit, confirm after a code change, delete.
import React, { useEffect, useState } from "react";
import { businessApi } from "./api.js";
import { Button, IconButton, TextField } from "../../md/react.jsx";
import { RichText } from "./common.jsx";

function Citations({ items }) {
  if (!items?.length) return null;
  return <ul className="cm-note__cites">
    {items.map((cite, index) => <li key={index} className="cm-small md-muted">
      <md-icon>description</md-icon><span>{[cite.doc, cite.section].filter(Boolean).join(" · ")}{cite.quote ? ` «${cite.quote}»` : ""}</span>
    </li>)}
  </ul>;
}

function NoteRow({ note, onChanged, notify }) {
  const [draft, setDraft] = useState(null);
  const [busy, setBusy] = useState(false);
  async function act(promise, message) {
    setBusy(true);
    try { await promise; notify?.(message); setDraft(null); onChanged(); } catch (reason) { notify?.(reason.message); } finally { setBusy(false); }
  }
  if (draft != null) {
    return <div className="cm-note cm-edit">
      <TextField label="Ghi chú" type="textarea" rows={4} value={draft} onChange={setDraft} maxLength={8000} />
      <span className="md-row cm-note__actions"><Button onClick={() => setDraft(null)}>Huỷ</Button>
        <Button variant="filled" icon="save" disabled={busy || !draft.trim()} onClick={() => act(businessApi.updateNote(note.id, { text: draft }), "Đã lưu ghi chú")}>Lưu</Button></span>
    </div>;
  }
  return <div className={`cm-note${note.by_ai ? " is-ai" : ""}`}>
    <RichText text={note.text} />
    <Citations items={note.citations} />
    {note.changed ? <div className="cm-link-row__notice"><md-icon>sync_problem</md-icon>
      <span className="cm-small">Code của node này đã đổi từ lúc ghi chú được lưu. Đọc lại rồi sửa, hoặc xác nhận vẫn đúng.</span>
      <Button icon="check" disabled={busy} onClick={() => act(businessApi.updateNote(note.id, {}), "Đã xác nhận ghi chú")}>Vẫn đúng</Button>
    </div> : null}
    <div className="cm-link-row__foot">
      <span className="md-muted cm-small">{note.by_ai ? "AI viết" : `Người viết${note.edited_by ? ` · ${note.edited_by}` : ""}`}</span>
      <span className="md-row">
        <IconButton icon="edit" label="Sửa ghi chú" disabled={busy} onClick={() => setDraft(note.text)} />
        <IconButton icon="delete" label="Xoá ghi chú" disabled={busy} onClick={() => act(businessApi.deleteNote(note.id), "Đã xoá ghi chú")} />
      </span>
    </div>
  </div>;
}

/** Notes on `nodeId`: shown on the node page and in the flow's node card. */
export function NodeNotes({ nodeId, notify, compact }) {
  const [notes, setNotes] = useState(null);
  const [tick, setTick] = useState(0);
  const [draft, setDraft] = useState(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    let live = true;
    businessApi.notes(nodeId).then((body) => { if (live) setNotes(body.notes); }).catch(() => { if (live) setNotes([]); });
    return () => { live = false; };
  }, [nodeId, tick]);
  const reload = () => setTick((value) => value + 1);
  async function add() {
    setBusy(true);
    try { await businessApi.createNote(nodeId, draft); notify?.("Đã thêm ghi chú"); setDraft(null); reload(); }
    catch (reason) { notify?.(reason.message); } finally { setBusy(false); }
  }
  if (notes == null) return null;
  if (compact && !notes.length && draft == null) {
    return <span><Button icon="note_add" onClick={() => setDraft("")}>Thêm ghi chú nghiệp vụ</Button></span>;
  }
  return <div className="cm-notes"><span className="cm-label">Ghi chú nghiệp vụ{notes.length ? ` (${notes.length})` : ""}</span>
    {!notes.length && draft == null ? <p className="md-muted cm-small">Chưa có ghi chú. Ghi lại node này có ý nghĩa gì với nghiệp vụ (màn hình, bảng, job dùng để làm gì).</p> : null}
    {notes.map((note) => <NoteRow key={note.id} note={note} notify={notify} onChanged={reload} />)}
    {draft != null ? <div className="cm-note cm-edit">
      <TextField label="Ghi chú mới" type="textarea" rows={4} value={draft} onChange={setDraft} maxLength={8000}
        supportingText="Cách đoạn bằng một dòng trống, **chữ** để nhấn mạnh." />
      <span className="md-row cm-note__actions"><Button onClick={() => setDraft(null)}>Huỷ</Button>
        <Button variant="filled" icon="save" disabled={busy || !draft.trim()} onClick={add}>Lưu</Button></span>
    </div> : <span><Button icon="note_add" onClick={() => setDraft("")}>Thêm ghi chú</Button></span>}
  </div>;
}
