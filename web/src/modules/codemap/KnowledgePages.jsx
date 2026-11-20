import React, { useCallback, useEffect, useState } from "react";
import { businessApi, currentUser } from "./api.js";
import { Button, Chip, ErrorBanner, FilterBar, Loading, Tabs, TextField } from "../../md/react.jsx";
import { KnowledgeShare } from "./Links.jsx";
import { Kind } from "./common.jsx";

// Rules / decisions / questions and the knowledge-base status page. Nothing is approved: a rule is in use when
// saved (by a person or AI). Answering a question or deciding a decision records a name (toolbar).

export const RULE_STATUS_LABELS = {
  approved: "Đang dùng",
  needs_review: "Code đã đổi · cần xem lại",
  retired: "Ngừng dùng",
};
const SOURCE_LABELS = { ai: "AI viết", sme: "Người viết", doc: "Từ tài liệu", code: "Từ code" };
const DECISION_LABELS = { proposed: "Chờ quyết định", accepted: "Đã chốt", rejected: "Không chọn", superseded: "Đã thay thế" };
const QUESTION_LABELS = { open: "Chờ trả lời", answered: "Đã trả lời", dropped: "Đã bỏ" };

function useLoad(load, deps) {
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  const reload = useCallback(() => {
    setError("");
    return load().then(setData).catch((reason) => setError(reason.message));
  }, deps); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { reload(); }, [reload]);
  return { data, error, reload };
}

function needName(notify) {
  if (currentUser()) return false;
  notify("Nhập tên của bạn ở thanh công cụ trước: câu trả lời và quyết định ghi lại người trả lời.");
  return true;
}

function Pill({ kind, children }) {
  return <span className={`cm-status cm-status--kn-${kind}`}>{children}</span>;
}

function Nodes({ ids = [], names = {}, onOpenNode }) {
  if (!ids.length) return null;
  return <span className="cm-kn__nodes">{ids.map((nodeId) => <button key={nodeId} type="button" className="cm-ref" onClick={() => onOpenNode(nodeId)} title={nodeId}>
    {names[nodeId] || nodeId}
  </button>)}</span>;
}

// --------------------------------------------------------------------------- rules

function RuleEditor({ rule, onSave, onCancel }) {
  const [draft, setDraft] = useState({
    title: rule?.title || "", text: rule?.text || "", evidence: rule?.evidence || "", domain: rule?.domain || "",
    nodes: (rule?.node_ids || []).join(", "),
  });
  const field = (key) => ({ value: draft[key], onChange: (value) => setDraft({ ...draft, [key]: value }) });
  function submit() {
    const body = { title: draft.title, text: draft.text, evidence: draft.evidence,
      nodes: draft.nodes.split(",").map((value) => value.trim()).filter(Boolean) };
    if (!rule) body.domain = draft.domain;
    onSave(body);
  }
  return <div className="cm-edit">
    <TextField label="Quy tắc (một câu khẳng định)" placeholder="Đơn đã giao không được hủy" {...field("title")} />
    <TextField label="Giải thích" type="textarea" rows={3} placeholder="Không đạt thì sao, ngoại lệ là gì" {...field("text")} />
    <div className="cm-kn__grid">
      <TextField label="Evidence (file:dòng)" placeholder="order-db/order_flow.sql:112" {...field("evidence")} />
      {!rule ? <TextField label="Domain" placeholder="ORD" {...field("domain")} /> : null}
    </div>
    <TextField label="Node hiện thực quy tắc" placeholder="PKG_ORDER.CANCEL_ORDER, ORDER_HEADER" {...field("nodes")}
      supportingText="Tên kỹ thuật hoặc node id, cách nhau bằng dấu phẩy. Khi code của các node này đổi hành vi, quy tắc được đánh dấu “Code đã đổi”." />
    <div className="cm-edit__foot"><span /><span className="md-row"><Button onClick={onCancel}>Huỷ</Button>
      <Button variant="filled" icon="save" onClick={submit} disabled={!draft.title.trim()}>Lưu</Button></span></div>
  </div>;
}

function RuleCard({ rule, onChanged, onOpenNode, notify }) {
  const [editing, setEditing] = useState(false);
  async function update(body, message) {
    try {
      await businessApi.updateRule(rule.rule_id, body);
      setEditing(false);
      notify(message);
      onChanged();
    } catch (reason) { notify(reason.message); }
  }
  if (editing) return <RuleEditor rule={rule} onSave={(body) => update(body, "Đã lưu")} onCancel={() => setEditing(false)} />;
  return <div className={`cm-kn__card cm-kn__card--${rule.status}`}>
    <div className="cm-kn__card-h"><code>{rule.rule_id}</code><b>{rule.title}</b><Pill kind={rule.status}>{RULE_STATUS_LABELS[rule.status] || rule.status}</Pill></div>
    {rule.status === "needs_review" && rule.review_reason ? <p className="cm-kn__reason"><md-icon>warning</md-icon>{rule.review_reason}</p> : null}
    {rule.text ? <p>{rule.text}</p> : null}
    <div className="cm-kn__meta">
      <span>Evidence: {rule.evidence ? <code>{rule.evidence}</code> : <em>chưa có</em>}</span>
      <span>Nguồn: {SOURCE_LABELS[rule.source] || rule.source}{rule.proposed_by ? ` · ${rule.proposed_by}` : ""}</span>
      <Nodes ids={rule.node_ids} names={rule.node_names} onOpenNode={onOpenNode} />
    </div>
    <div className="md-row">
      {rule.status === "needs_review" ? <Button variant="filled" icon="task_alt" onClick={() => update({ status: "approved" }, `${rule.rule_id}: vẫn đúng với code hiện tại`)}>Vẫn đúng</Button> : null}
      {rule.status === "retired" ? <Button icon="undo" onClick={() => update({ status: "approved" }, `${rule.rule_id} dùng lại`)}>Dùng lại</Button> : null}
      <Button variant="outlined" icon="edit" onClick={() => setEditing(true)}>Sửa</Button>
      {rule.status !== "retired" ? <Button icon="block" onClick={() => update({ status: "retired" }, `${rule.rule_id} ngừng dùng`)}>Ngừng dùng</Button> : null}
    </div>
  </div>;
}

// --------------------------------------------------------------------------- questions and decisions

function QuestionCard({ question, onChanged, onOpenNode, notify }) {
  const [answer, setAnswer] = useState("");
  async function send(body, message) {
    if (needName(notify)) return;
    try {
      await businessApi.answerQuestion(question.question_id, body);
      notify(message);
      onChanged();
    } catch (reason) { notify(reason.message); }
  }
  return <div className="cm-kn__card">
    <div className="cm-kn__card-h"><code>{question.question_id}</code><b>{question.text}</b><Pill kind={question.status}>{QUESTION_LABELS[question.status]}</Pill></div>
    {question.context ? <p className="md-muted">{question.context}</p> : null}
    <div className="cm-kn__meta"><span>Hỏi bởi {question.asked_by || "?"}</span><Nodes ids={question.node_ids} names={question.node_names} onOpenNode={onOpenNode} /></div>
    {question.status === "answered" ? <AnswerText question={question} /> : null}
    {question.status === "open" ? <>
      {question.options?.length ? <md-chip-set class="cm-kn__options">{question.options.map((option) => <Chip key={option.title}
        selected={answer === option.title} onClick={() => setAnswer(option.title)} title={option.consequence || ""}>
        {option.consequence ? `${option.title} · ${option.consequence}` : option.title}</Chip>)}</md-chip-set> : null}
      <TextField label="Câu trả lời" type="textarea" rows={2} value={answer} onChange={setAnswer} supportingText="AI sẽ coi là sự thật và không hỏi lại" />
      <div className="md-row">
        <Button variant="filled" icon="check" disabled={!answer.trim()} onClick={() => send({ answer }, `Đã trả lời ${question.question_id}`)}>Trả lời</Button>
        <Button icon="close" onClick={() => send({ status: "dropped" }, `Đã bỏ ${question.question_id}`)}>Bỏ câu hỏi</Button>
      </div>
    </> : null}
  </div>;
}

// The answer, with the option and document citations when an agent wrote it (answer_meta.source 'ai').
function AnswerText({ question }) {
  const meta = question.answer_meta || {};
  const citations = meta.citations || [];
  return <div className="cm-answer">
    <b>Trả lời ({question.answered_by}{meta.source === "ai" ? ", AI viết" : ""}):</b> {meta.option ? <>[{meta.option}] </> : null}{question.answer}
    {citations.length ? <ul className="md-muted">{citations.map((citation, index) => <li key={index}>
      {citation.url ? <a href={citation.url} target="_blank" rel="noreferrer">{citation.doc}</a> : citation.doc} · {citation.section}
      {citation.quote ? <> · “{citation.quote}”</> : null}</li>)}</ul> : null}
  </div>;
}

function DecisionCard({ decision, onChanged, onOpenNode, notify }) {
  const [text, setText] = useState(decision.decision || "");
  const [reason, setReason] = useState(decision.reason || "");
  async function decide(status) {
    if (needName(notify)) return;
    try {
      await businessApi.updateDecision(decision.decision_id, { status, decision: text, reason });
      notify(status === "accepted" ? `Đã chốt ${decision.decision_id}` : `Đã từ chối ${decision.decision_id}`);
      onChanged();
    } catch (failure) { notify(failure.message); }
  }
  return <div className="cm-kn__card">
    <div className="cm-kn__card-h"><code>{decision.decision_id}</code><b>{decision.title}</b><Pill kind={decision.status}>{DECISION_LABELS[decision.status]}</Pill></div>
    {decision.context ? <p>{decision.context}</p> : null}
    {decision.options?.length ? <ol className="cm-kn__option-list">{decision.options.map((option) => <li key={option.title}>
      <button type="button" className="cm-link" onClick={() => setText(option.title)} disabled={decision.status !== "proposed"}>{option.title}</button>
      {option.consequence ? <span className="md-muted"> · {option.consequence}</span> : null}</li>)}</ol> : null}
    <div className="cm-kn__meta"><Nodes ids={decision.node_ids} names={decision.node_names} onOpenNode={onOpenNode} />
      {decision.decided_by ? <span>Quyết định bởi {decision.decided_by}</span> : null}</div>
    {decision.status === "proposed" ? <>
      <TextField label="Quyết định" type="textarea" rows={2} value={text} onChange={setText} />
      <TextField label="Lý do" type="textarea" rows={2} value={reason} onChange={setReason} />
      <div className="md-row">
        <Button variant="filled" icon="gavel" disabled={!text.trim()} onClick={() => decide("accepted")}>Chốt</Button>
        <Button icon="close" onClick={() => decide("rejected")}>Từ chối</Button>
      </div>
    </> : decision.decision ? <p className="cm-answer"><b>Quyết định:</b> {decision.decision}{decision.reason ? <><br /><b>Lý do:</b> {decision.reason}</> : null}</p> : null}
  </div>;
}

// --------------------------------------------------------------------------- pages

const TABS = [["rules", "Quy tắc", "balance"], ["decisions", "Quyết định", "gavel"], ["questions", "Câu hỏi", "help"]];

export function KnowledgePage({ onOpenNode, notify }) {
  const [tab, setTab] = useState("rules");
  const [status, setStatus] = useState("");
  const [creating, setCreating] = useState(false);
  const load = () => (tab === "rules" ? businessApi.rules(status ? { status } : {})
    : tab === "decisions" ? businessApi.decisions(status ? { status } : {}) : businessApi.questions(status ? { status } : {}));
  const { data, error, reload } = useLoad(load, [tab, status]);
  const statuses = tab === "rules" ? RULE_STATUS_LABELS : tab === "decisions" ? DECISION_LABELS : QUESTION_LABELS;
  const props = { onChanged: reload, onOpenNode, notify };

  async function create(body) {
    try {
      const created = tab === "rules" ? await businessApi.createRule(body)
        : tab === "decisions" ? await businessApi.createDecision(body) : await businessApi.createQuestion(body);
      setCreating(false);
      notify(`Đã tạo ${created.rule_id || created.decision_id || created.question_id}`);
      reload();
    } catch (reason) { notify(reason.message); }
  }

  return <article className="cm-page cm-page--wide">
    <header className="cm-page__head">
      <Kind icon="balance">Kiến thức</Kind>
      <h1>Quy tắc, quyết định và câu hỏi</h1>
      <p className="cm-lead">Kiến thức chỉ con người nói được, gắn với node trong graph. Lưu là dùng ngay, ghi rõ ai viết (người hay AI); MCP server trả về cho AI kèm nguồn.</p>
    </header>
    <Tabs tabs={TABS} value={tab} onChange={(key) => { setTab(key); setStatus(""); setCreating(false); }} />
    <div className="cm-kn__toolbar">
      <div className="cm-kn__filters"><FilterBar key={tab} panelId="cm-kn-filter" summary={data ? `${data.length} mục` : ""}
        filters={[{ key: "status", label: "Trạng thái", value: status, defaultValue: "", options: [["", "Mọi trạng thái"], ...Object.entries(statuses)] }]}
        onApply={(values) => setStatus(values.status)} /></div>
      <Button variant="tonal" icon="add" onClick={() => setCreating(!creating)}>Thêm</Button>
    </div>
    {creating ? (tab === "rules" ? <RuleEditor onSave={create} onCancel={() => setCreating(false)} />
      : <SimpleCreate kind={tab} onSave={create} onCancel={() => setCreating(false)} />) : null}
    {error ? <ErrorBanner>{error}</ErrorBanner> : !data ? <Loading />
      : !data.length ? <p className="md-muted">Chưa có mục nào.</p>
        : <div className="cm-kn__list">{data.map((item) => tab === "rules" ? <RuleCard key={item.rule_id} rule={item} {...props} />
          : tab === "decisions" ? <DecisionCard key={item.decision_id} decision={item} {...props} />
            : <QuestionCard key={item.question_id} question={item} {...props} />)}</div>}
  </article>;
}

function SimpleCreate({ kind, onSave, onCancel }) {
  const [draft, setDraft] = useState({ title: "", context: "", options: "", nodes: "" });
  const field = (key) => ({ value: draft[key], onChange: (value) => setDraft({ ...draft, [key]: value }) });
  const list = (value) => value.split(/\n|,/).map((item) => item.trim()).filter(Boolean);
  function submit() {
    const common = { context: draft.context, nodes: list(draft.nodes), options: list(draft.options).map((title) => ({ title })) };
    onSave(kind === "decisions" ? { ...common, title: draft.title } : { ...common, text: draft.title });
  }
  return <div className="cm-edit">
    <TextField label={kind === "decisions" ? "Cần quyết định gì" : "Câu hỏi"} {...field("title")} />
    <TextField label="Bối cảnh" type="textarea" rows={3} {...field("context")} />
    <TextField label="Phương án (mỗi dòng một phương án)" type="textarea" rows={3} {...field("options")} />
    <TextField label="Node liên quan (tên kỹ thuật, cách nhau bằng dấu phẩy)" {...field("nodes")} />
    <div className="cm-edit__foot"><span /><span className="md-row"><Button onClick={onCancel}>Huỷ</Button>
      <Button variant="filled" icon="save" onClick={submit} disabled={!draft.title.trim()}>Lưu</Button></span></div>
  </div>;
}

function freshness(stale) {
  const commits = [...new Set((stale.revisions || []).map((item) => String(item.commit || "").slice(0, 8)).filter(Boolean))];
  const built = `Graph extract lúc ${String(stale.generated_at || "?").replace("T", " ").slice(0, 16)}${commits.length ? ` từ commit ${commits.join(", ")}` : ""}`;
  if (stale.fresh === null || stale.fresh === undefined) return `${built} · dữ liệu đóng gói trong pack, không so được với code đang sửa.`;
  if (stale.fresh) return `${built} · khớp với code hiện tại.`;
  const counts = stale.counts || {};
  return `${built} · ĐÃ CŨ: ${counts.changed || 0} file đã sửa, ${counts.deleted || 0} file đã xoá, ${counts.added || 0} file mới. Hãy chạy extract lại.`;
}

export function KbStatusPage({ onOpenKnowledge, mcpUrl, notify }) {
  const { data, error, reload } = useLoad(() => businessApi.kbStatus(), []);
  if (error) return <div className="cm-page"><ErrorBanner>{error}</ErrorBanner></div>;
  if (!data) return <div className="cm-page"><Loading /></div>;
  const stale = data.stale || {};
  const counts = stale.counts || {};
  const open = data.open || {};
  return <article className="cm-page cm-page--wide">
    <header className="cm-page__head">
      <Kind icon="monitoring">Kiến thức</Kind>
      <h1>Tình trạng knowledge base</h1>
      <p className="cm-lead">{freshness(stale)}</p>
      <div className="md-row"><Button variant="outlined" icon="refresh" onClick={reload}>Tải lại</Button>
        <Button variant="tonal" icon="balance" onClick={onOpenKnowledge}>Quy tắc, câu hỏi</Button></div>
    </header>
    <div className="cm-stats cm-stats--auto">
      <div className={counts.changed ? "is-warn" : ""}><b>{counts.changed ?? "–"}</b><span>file đã sửa từ lúc extract</span></div>
      <div className={counts.added ? "is-warn" : ""}><b>{counts.added ?? "–"}</b><span>file mới chưa có trong graph</span></div>
      <div className={open.rules_needs_review ? "is-warn" : ""}><b>{open.rules_needs_review ?? 0}</b><span>quy tắc có code đã đổi</span></div>
      <div className={open.questions_open ? "is-warn" : ""}><b>{open.questions_open ?? 0}</b><span>câu hỏi chờ trả lời</span></div>
    </div>
    <KnowledgeShare notify={notify} onImported={reload} />
    <section className="cm-kn__section"><h2><md-icon>commit</md-icon>Source và commit</h2>
      <div className="md-table-wrap"><table className="md-table"><thead><tr><th>Source</th><th>Commit lúc extract</th><th>Branch</th><th>Commit mới từ đó</th></tr></thead>
        <tbody>{(stale.revisions || []).map((item) => <tr key={item.source}><td>{item.source}</td>
          <td><code>{item.vcs === "none" ? "không có git" : String(item.commit || "").slice(0, 10)}</code>{item.dirty_at_extract ? " (có sửa chưa commit)" : ""}</td>
          <td>{item.branch || ""}</td><td>{item.commits_since ?? "–"}</td></tr>)}</tbody></table></div>
      {(stale.changed || []).length ? <details className="cm-kn__details"><summary>File đã sửa ({stale.changed.length})</summary>
        <ul>{stale.changed.map((path) => <li key={path}><code>{path}</code></li>)}</ul></details> : null}
      {(stale.added || []).length ? <details className="cm-kn__details"><summary>File mới ({stale.added.length})</summary>
        <ul>{stale.added.map((path) => <li key={path}><code>{path}</code></li>)}</ul></details> : null}
    </section>
    <section className="cm-kn__section"><h2><md-icon>verified</md-icon>Chất lượng extract</h2>
      <div className="md-table-wrap"><table className="md-table"><tbody>{Object.entries(data.quality || {}).map(([key, value]) => <tr key={key}><td>{key}</td><td className="md-table__num">{String(value)}</td></tr>)}</tbody></table></div>
    </section>
    <section className="cm-kn__section"><h2><md-icon>smart_toy</md-icon>AI agent dùng KB thế nào (30 ngày)</h2>
      <p className="md-muted cm-small">MCP over HTTP: <code>{new URL(mcpUrl, window.location.origin).href}</code> · stdio: <code>viewer-hub mcp codemap</code></p>
      {(data.usage?.by_tool || []).length ? <div className="md-table-wrap"><table className="md-table"><thead><tr><th>Tool</th><th className="md-table__num">Lượt gọi</th><th className="md-table__num">Không có kết quả</th><th className="md-table__num">Người dùng</th></tr></thead>
        <tbody>{data.usage.by_tool.map((row) => <tr key={row.tool}><td><code>{row.tool}</code></td><td className="md-table__num">{row.calls}</td><td className="md-table__num">{row.empty}</td><td className="md-table__num">{row.users}</td></tr>)}</tbody></table></div>
        : <p className="md-muted cm-small">Chưa có lượt gọi MCP nào.</p>}
      {(data.usage?.unanswered || []).length ? <>
        <p className="md-muted cm-small">Câu hỏi không có kết quả: chỗ KB đang thiếu (thuật ngữ chưa có trong từ điển, source chưa extract…).</p>
        <ul className="cm-kn__unanswered">{data.usage.unanswered.map((row, index) => <li key={index}><code>{row.tool}</code> {row.arguments} <span className="md-muted">×{row.count}</span></li>)}</ul>
      </> : null}
    </section>
  </article>;
}
