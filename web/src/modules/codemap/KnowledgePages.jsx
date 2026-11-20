import React, { useCallback, useEffect, useState } from "react";
import { businessApi, currentUser } from "./api.js";
import { Button, Checkbox, Chip, ErrorBanner, FilterBar, Loading, Tabs, TextField } from "../../md/react.jsx";
import { KnowledgeShare, LinkRow } from "./Links.jsx";
import { Kind } from "./common.jsx";

// Review queue, rules / decisions / questions and the knowledge-base status page.
// Approving needs a name (toolbar); the backend refuses an approval without one.

export const RULE_STATUS_LABELS = {
  draft: "Bản nháp · chưa duyệt",
  approved: "Đã duyệt",
  needs_review: "Code đã đổi · cần duyệt lại",
  retired: "Ngừng dùng",
};
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
  notify("Nhập tên của bạn ở thanh công cụ trước khi duyệt: lần duyệt ghi lại người duyệt.");
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

function Section({ icon, title, count, hint, children }) {
  return <section className="cm-kn__section">
    <h2><md-icon>{icon}</md-icon>{title}<span className="md-badge">{count}</span></h2>
    {hint ? <p className="md-muted cm-small">{hint}</p> : null}
    {count ? <div className="cm-kn__list">{children}</div> : <p className="md-muted cm-small">Không có mục nào.</p>}
  </section>;
}

// --------------------------------------------------------------------------- rules

function RuleEditor({ rule, onSave, onCancel }) {
  const [draft, setDraft] = useState({
    title: rule?.title || "", text: rule?.text || "", evidence: rule?.evidence || "", domain: rule?.domain || "",
    nodes: (rule?.node_ids || []).join(", "), approve: false,
  });
  const field = (key) => ({ value: draft[key], onChange: (value) => setDraft({ ...draft, [key]: value }) });
  function submit() {
    const body = { title: draft.title, text: draft.text, evidence: draft.evidence,
      nodes: draft.nodes.split(",").map((value) => value.trim()).filter(Boolean) };
    if (!rule) body.domain = draft.domain;
    if (!rule && draft.approve) body.status = "approved";
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
      supportingText="Tên kỹ thuật hoặc node id, cách nhau bằng dấu phẩy. Khi code của các node này đổi hành vi, quy tắc đã duyệt tự quay về hàng chờ duyệt." />
    {!rule ? <Checkbox checked={draft.approve} onChange={(approve) => setDraft({ ...draft, approve })} label="Duyệt luôn (tôi là người nắm nghiệp vụ này)" /> : null}
    <div className="cm-edit__foot"><span /><span className="md-row"><Button onClick={onCancel}>Huỷ</Button>
      <Button variant="filled" icon="save" onClick={submit} disabled={!draft.title.trim()}>Lưu</Button></span></div>
  </div>;
}

function RuleCard({ rule, onChanged, onOpenNode, notify }) {
  const [editing, setEditing] = useState(false);
  async function update(body, message) {
    if (body.status === "approved" && needName(notify)) return;
    try {
      await businessApi.updateRule(rule.rule_id, body);
      setEditing(false);
      notify(message);
      onChanged();
    } catch (reason) { notify(reason.message); }
  }
  if (editing) return <RuleEditor rule={rule} onSave={(body) => update(body, "Đã lưu; quy tắc cần được duyệt lại")} onCancel={() => setEditing(false)} />;
  return <div className={`cm-kn__card cm-kn__card--${rule.status}`}>
    <div className="cm-kn__card-h"><code>{rule.rule_id}</code><b>{rule.title}</b><Pill kind={rule.status}>{RULE_STATUS_LABELS[rule.status] || rule.status}</Pill></div>
    {rule.status === "needs_review" && rule.review_reason ? <p className="cm-kn__reason"><md-icon>warning</md-icon>{rule.review_reason}</p> : null}
    {rule.text ? <p>{rule.text}</p> : null}
    <div className="cm-kn__meta">
      <span>Evidence: {rule.evidence ? <code>{rule.evidence}</code> : <em>chưa có</em>}</span>
      <span>Nguồn: {rule.source}{rule.proposed_by ? ` · đề xuất bởi ${rule.proposed_by}` : ""}{rule.approved_by ? ` · duyệt bởi ${rule.approved_by}` : ""}</span>
      <Nodes ids={rule.node_ids} names={rule.node_names} onOpenNode={onOpenNode} />
    </div>
    <div className="md-row">
      {rule.status !== "approved" ? <Button variant="filled" icon="check" onClick={() => update({ status: "approved" }, `Đã duyệt ${rule.rule_id}`)}>{rule.status === "needs_review" ? "Vẫn đúng · duyệt lại" : "Duyệt"}</Button> : null}
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
    {question.status === "answered" ? <p className="cm-answer"><b>Trả lời ({question.answered_by}):</b> {question.answer}</p> : null}
    {question.status === "open" && question.proposed_answer ? <ProposedAnswer proposal={question.proposed_answer} onUse={setAnswer} /> : null}
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

// An agent's answer from the business documents: shown under the question until a person answers it.
function ProposedAnswer({ proposal, onUse }) {
  const citations = proposal.citations || [];
  return <div className="cm-answer">
    <b>AI đề xuất ({proposal.proposed_by || "?"}, chưa xác nhận):</b> {proposal.option ? <>[{proposal.option}] </> : null}{proposal.answer}
    {citations.length ? <ul className="md-muted">{citations.map((citation, index) => <li key={index}>
      {citation.url ? <a href={citation.url} target="_blank" rel="noreferrer">{citation.doc}</a> : citation.doc} · {citation.section}
      {citation.quote ? <> · “{citation.quote}”</> : null}</li>)}</ul> : null}
    <div className="md-row"><Button icon="content_copy" onClick={() => onUse(proposal.option ? `${proposal.option}: ${proposal.answer}` : proposal.answer)}>Dùng câu trả lời này</Button></div>
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

export function ReviewPage({ onOpenItem, onOpenNode, notify }) {
  const { data, error, reload } = useLoad(() => businessApi.reviewQueue(), []);
  if (error) return <div className="cm-page"><ErrorBanner>{error}</ErrorBanner></div>;
  if (!data) return <div className="cm-page"><Loading /></div>;
  const props = { onChanged: reload, onOpenNode, notify };
  const flowLink = (part) => <button key={`${part.flow_id}:${part.part}`} type="button" className="cm-card" onClick={() => onOpenItem({ kind: "flow", id: part.flow_id })}>
    <span className="cm-card__h"><b>{part.flow_name || part.flow_id}</b><span className="md-muted cm-small">{part.part}</span></span>
    <span className="cm-card__meta"><span>{part.title}</span></span>
  </button>;
  return <article className="cm-page cm-page--wide">
    <header className="cm-page__head">
      <Kind icon="balance">Kiến thức</Kind>
      <h1>Chờ duyệt</h1>
      <p className="cm-lead">Mọi thứ AI đề xuất và mọi kiến thức đã duyệt mà code đã đổi từ lúc duyệt. AI không tự duyệt được gì; câu trả lời và quyết định ở đây trở thành sự thật cho mọi agent.</p>
      <div className="md-row"><Button variant="outlined" icon="refresh" onClick={reload}>Tải lại</Button></div>
    </header>
    <Section icon="warning" title="Quy tắc đã duyệt nhưng code đã đổi" count={data.rules_needs_review.length}
      hint="Hành vi của node hiện thực quy tắc đã khác lúc duyệt. Đọc lại code (evidence) rồi duyệt lại, sửa hoặc ngừng dùng.">
      {data.rules_needs_review.map((rule) => <RuleCard key={rule.rule_id} rule={rule} {...props} />)}
    </Section>
    <Section icon="help" title="Câu hỏi chờ trả lời" count={data.questions_open.length}>
      {data.questions_open.map((question) => <QuestionCard key={question.question_id} question={question} {...props} />)}
    </Section>
    <Section icon="gavel" title="Quyết định chờ chốt" count={data.decisions_proposed.length}>
      {data.decisions_proposed.map((decision) => <DecisionCard key={decision.decision_id} decision={decision} {...props} />)}
    </Section>
    <Section icon="balance" title="Quy tắc AI đề xuất" count={data.rules_draft.length}>
      {data.rules_draft.map((rule) => <RuleCard key={rule.rule_id} rule={rule} {...props} />)}
    </Section>
    <Section icon="warning" title="Tài liệu luồng đã duyệt nhưng code đã đổi" count={data.flow_parts_changed.length}>
      {data.flow_parts_changed.map(flowLink)}
    </Section>
    <Section icon="description" title="Tài liệu luồng AI viết, chưa duyệt" count={data.flow_parts_ai.length}>
      {data.flow_parts_ai.map(flowLink)}
    </Section>
    <Section icon="add_link" title="Liên kết AI đề xuất" count={(data.links_proposed || []).length}
      hint="Cạnh AI thấy còn thiếu trong graph (gọi động, job theo cấu hình…). Chỉ khi duyệt, luồng mới đi qua cạnh này.">
      {(data.links_proposed || []).map((link) => <LinkRow key={link.link_id} link={{ ...link, status: "proposed" }} onChanged={reload} onOpenNode={onOpenNode} notify={notify} />)}
    </Section>
  </article>;
}

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
    if (body.status === "approved" && needName(notify)) return;
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
      <p className="cm-lead">Kiến thức chỉ con người nói được, gắn với node trong graph. MCP server trả về cho AI kèm trạng thái duyệt.</p>
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

export function KbStatusPage({ onReview, mcpUrl, notify }) {
  const { data, error, reload } = useLoad(() => businessApi.kbStatus(), []);
  if (error) return <div className="cm-page"><ErrorBanner>{error}</ErrorBanner></div>;
  if (!data) return <div className="cm-page"><Loading /></div>;
  const stale = data.stale || {};
  const counts = stale.counts || {};
  const review = data.review || {};
  const waiting = Object.values(review).reduce((sum, value) => sum + value, 0);
  return <article className="cm-page cm-page--wide">
    <header className="cm-page__head">
      <Kind icon="monitoring">Kiến thức</Kind>
      <h1>Tình trạng knowledge base</h1>
      <p className="cm-lead">{freshness(stale)}</p>
      <div className="md-row"><Button variant="outlined" icon="refresh" onClick={reload}>Tải lại</Button>
        <Button variant="tonal" icon="inbox" onClick={onReview}>Chờ duyệt: {waiting}</Button></div>
    </header>
    <div className="cm-stats cm-stats--auto">
      <div className={counts.changed ? "is-warn" : ""}><b>{counts.changed ?? "–"}</b><span>file đã sửa từ lúc extract</span></div>
      <div className={counts.added ? "is-warn" : ""}><b>{counts.added ?? "–"}</b><span>file mới chưa có trong graph</span></div>
      <div className={review.rules_needs_review ? "is-warn" : ""}><b>{review.rules_needs_review ?? 0}</b><span>quy tắc cần duyệt lại</span></div>
      <div className={review.questions_open ? "is-warn" : ""}><b>{review.questions_open ?? 0}</b><span>câu hỏi chờ trả lời</span></div>
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
