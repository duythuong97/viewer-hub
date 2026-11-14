// Search results, flat or grouped, with pagination. Snippets and highlighted titles are HTML from the server's
// highlighter: the document text HTML-escaped with <mark> around matches (viewer_hub/fsearch/highlight.py).
import React from "react";
import { http } from "../../app/http.js";

const ICONS = { pdf: "picture_as_pdf", md: "article", txt: "description", html: "html", py: "code", js: "javascript", ts: "code",
  java: "code", go: "code", cs: "code", sql: "database", xlsx: "table", xls: "table", docx: "description", pptx: "slideshow",
  png: "image", jpg: "image", jpeg: "image" };

const marked = (html) => ({ __html: html });

async function copy(path) {
  try {
    await navigator.clipboard.writeText(path);
    window.md?.snackbar("Đã sao chép đường dẫn");
  } catch {
    window.md?.snackbar(path);
  }
}

async function reveal(path) {
  try {
    await http.get("/ocr-search/api/open-file", { path });
    window.md?.snackbar("Đã mở thư mục chứa file");
  } catch (error) {
    window.md?.snackbar(error.body?.error || error.message);
  }
}

function Result({ doc, nested }) {
  const title = doc.titleHtml ? <span dangerouslySetInnerHTML={marked(doc.titleHtml)} /> : doc.title;
  return <li className={`md-result${nested ? " md-result--nested" : ""}`}>
    <div className="md-result__head">
      <md-icon class="md-result__icon">{ICONS[doc.fileType.toLowerCase()] || "draft"}</md-icon>
      <div className="md-result__title-wrap">
        <h3 className="md-result__title">{doc.href ? <a href={doc.href} target="_blank" rel="noopener noreferrer">{title}</a> : title}</h3>
        {doc.path ? <div className="md-result__path">{doc.path}</div> : null}
      </div>
    </div>
    {doc.snippets.length && doc.kind === "code" ? <div className="md-code-snippets">
      {doc.snippets.slice(0, nested ? 1 : 2).map((snip, i) => <pre key={i} className="md-result__code" tabIndex={0} dangerouslySetInnerHTML={marked(snip)} />)}
    </div> : doc.snippets.length ? <div className="md-result__snippet">
      {doc.kind === "ocr" ? <span className="md-badge"><md-icon style={{ "--md-icon-size": "16px" }}>document_scanner</md-icon>OCR</span> : null}
      {doc.snippets.slice(0, nested ? 2 : 3).map((snip, i) => <p key={i} dangerouslySetInnerHTML={marked(`…${snip}…`)} />)}
    </div> : doc.plain ? (doc.kind === "code" ? <pre className="md-result__code" tabIndex={0}>{doc.plain}</pre>
      : <p className="md-result__snippet">{doc.plain}…</p>) : null}
    <div className="md-result__meta">
      {doc.repository ? <span className="md-badge"><md-icon style={{ "--md-icon-size": "16px" }}>folder</md-icon>{doc.repository}</span> : null}
      {doc.fileType ? <span className="md-badge">{doc.fileType}</span> : null}
      {doc.author ? <span className="md-badge"><md-icon style={{ "--md-icon-size": "16px" }}>person</md-icon>{doc.author}</span> : null}
      {doc.modified ? <span className="md-badge"><md-icon style={{ "--md-icon-size": "16px" }}>schedule</md-icon>{doc.modified}</span> : null}
      <span className="md-spacer"></span>
      {doc.path ? <md-icon-button aria-label="Sao chép đường dẫn" title="Sao chép đường dẫn" onClick={() => copy(doc.path)}><md-icon>content_copy</md-icon></md-icon-button> : null}
      {doc.path && doc.local ? <md-icon-button aria-label="Mở thư mục chứa file" title="Mở thư mục chứa file" onClick={() => reveal(doc.path)}><md-icon>folder_open</md-icon></md-icon-button> : null}
      {doc.href ? <md-icon-button href={doc.href} target="_blank" aria-label="Mở trong repository" title="Mở trong repository"><md-icon>open_in_new</md-icon></md-icon-button> : null}
    </div>
  </li>;
}

function Pages({ page, total, onPage }) {
  if (total <= 1) return null;
  const numbers = [];
  for (let n = Math.max(1, page - 2); n < Math.min(total + 1, page + 3); n += 1) numbers.push(n);
  return <nav className="md-row" style={{ justifyContent: "center", marginTop: 16 }} aria-label="Phân trang">
    <md-icon-button disabled={page <= 1 || undefined} aria-label="Trang trước" onClick={() => onPage(page - 1)}><md-icon>chevron_left</md-icon></md-icon-button>
    {numbers.map((n) => n === page ? <md-filled-tonal-button key={n}>{n}</md-filled-tonal-button>
      : <md-text-button key={n} onClick={() => onPage(n)}>{n}</md-text-button>)}
    <md-icon-button disabled={page >= total || undefined} aria-label="Trang sau" onClick={() => onPage(page + 1)}><md-icon>chevron_right</md-icon></md-icon-button>
  </nav>;
}

export default function Results({ result, debug, onPage }) {
  const empty = result.grouped ? !result.groups.length : !result.docs.length;
  return <>
    {result.notices.map((notice) => <div key={notice} className="md-banner"><md-icon>info</md-icon><div className="md-banner__text">{notice}</div></div>)}
    {result.error ? <div className="md-banner md-banner--error"><md-icon>error</md-icon><div className="md-banner__text">{result.error}</div></div> : <>
      {debug && result.engine ? <span className="md-badge" style={{ marginBottom: 8 }}>{result.engine}</span> : null}
      {result.grouped ? result.groups.map((group) => <details key={group.key} className="md-card md-card--outlined md-group" open>
        <summary className="md-group__summary">
          <md-icon>folder</md-icon><span className="md-title-small md-spacer">{group.key}</span>
          <span className="md-badge md-badge--primary">{group.count}</span>
        </summary>
        <ol className="md-results">{group.docs.map((doc) => <Result key={doc.id} doc={doc} nested />)}</ol>
        {group.count > 10 ? <p className="md-body-small md-muted" style={{ padding: "0 16px 12px" }}>+ {group.count - 10} kết quả khác trong nhóm này</p> : null}
      </details>) : result.docs.length ? <ol className="md-results md-card md-card--outlined">
        {result.docs.map((doc) => <Result key={doc.id} doc={doc} />)}
      </ol> : null}
      {empty ? <div className="md-empty"><md-icon>search_off</md-icon><h2>Không có kết quả</h2><p>Thử từ khoá rộng hơn, chuyển sang OR, hoặc bỏ bớt bộ lọc.</p></div> : null}
      <Pages page={result.page} total={result.totalPages} onPage={onPage} />
      {debug && result.debug ? <details className="md-card md-card--outlined" style={{ marginTop: 16, padding: "12px 16px" }}>
        <summary className="md-label-large">Debug</summary>
        <pre className="md-code">{JSON.stringify(result.debug, null, 2)}</pre>
      </details> : null}
    </>}
  </>;
}
