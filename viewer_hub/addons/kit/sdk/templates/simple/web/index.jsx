// Page of the template addon "my-addon". Default export = the page; the Hub passes { module, subpath, api, addon }.
// The Hub draws the page header (status, Nhật ký, Cài đặt) above this page; `api` calls this addon's own
// API (/x/my-addon/api/...). Text from the API is rendered as text, never as HTML.
// Do not redraw that header: no settings form or "not configured" banner, no Cài đặt / Nhật ký / run / stop buttons
// (refused at install). Settings live in addon.json `settings` (+ `required`); open the Hub's dialog with
// useAddon().openSettings(key). See AGENTS.md, top of the file.
import React, { useState } from "react";
import { Button, Empty, ErrorBanner, IconButton, Loading, TextField } from "@vh/md";
import { useAction, useConfirm, useLoad, useTitle } from "@vh/ui";

export default function NotesPage({ module, api }) {
  const { data, error, reload } = useLoad(() => api.get("/notes"), []);
  const [text, setText] = useState("");
  const [run, busy] = useAction();
  const [confirm, dialog] = useConfirm(); // dangerous actions ask first (AGENTS.md §6.1)
  useTitle(data?.title || "Ghi chú");
  const add = () => run(() => api.post("/notes", { text }), "Đã lưu").then((result) => {
    if (result) { setText(""); reload(); }
  });
  const remove = async (note) => {
    if (!(await confirm({ title: "Xoá ghi chú này?", text: "Ghi chú bị xoá hẳn, AI cũng không đọc được nữa.", confirm: "Xoá", icon: "delete" }))) return;
    run(() => api.delete(`/notes/${note.id}`), "Đã xoá").then(reload);
  };
  return <>
    {dialog}
    <div className="md-stack">
      <section className="md-card md-card--outlined">
        <div className="md-card__body md-stack">
          <TextField label="Ghi chú mới" type="textarea" rows={3} value={text} onChange={setText} maxLength={2000} />
          <div><Button variant="filled" icon="save" onClick={add} disabled={busy || !text.trim()}>Lưu</Button></div>
        </div>
      </section>
      {error ? <ErrorBanner>{error.message}</ErrorBanner> : null}
      {!data && !error ? <Loading /> : null}
      {data && !data.notes.length ? <Empty icon="sticky_note_2" title="Chưa có ghi chú" /> : null}
      {data?.notes.map((note) => <section key={note.id} className="md-card md-card--outlined">
        <div className="md-card__body">
          <div className="md-body-small md-muted">{note.at}</div>
          <p style={{ whiteSpace: "pre-wrap" }}>{note.text}</p>
        </div>
        <div className="md-card__actions">
          <IconButton icon="delete" danger label="Xoá ghi chú" onClick={() => remove(note)} />
        </div>
      </section>)}
    </div>
  </>;
}
