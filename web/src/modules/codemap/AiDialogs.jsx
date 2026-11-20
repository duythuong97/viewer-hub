import React, { useEffect, useRef, useState } from "react";
import { businessApi } from "./api.js";
import { Button, Checkbox, Dialog, ErrorBanner } from "../../md/react.jsx";
import { copyText, downloadText } from "./common.jsx";

// One dialog for the whole round trip with AI: 1) export a file, 2) paste what AI returned, 3) check and import.
// "Xuất cho AI" opens it at step 1, "Nhập kết quả AI" at step 2; copying or downloading moves on to step 2.

const OPTIONS = [
  ["instructions", "Kèm hướng dẫn cho AI", "File .md gồm hướng dẫn đầy đủ, phần dữ liệu và khối YAML là định dạng AI trả về. Bỏ chọn để chỉ lấy file YAML khi bạn tự viết prompt."],
  ["code", "Kèm đoạn code", "Cần để AI viết quy tắc có bằng chứng. Bỏ chọn nếu file quá lớn."],
  ["locked", "Gửi kèm phần người đã sửa", "Các phần này bị khoá, AI chỉ đọc để hiểu ngữ cảnh. Bỏ chọn thì AI viết lại cả những phần đó."],
];
const OVERVIEW_OPTIONS = OPTIONS.slice(0, 1);
const STEPS = [["Xuất file", "download"], ["Dán kết quả AI", "content_paste"], ["Kiểm tra và nhập", "fact_check"]];
const CHECK_ICONS = { ok: "check_circle", warn: "warning", error: "cancel" };

function Stepper({ step, onStep, reachable, listRef }) {
  return <ol ref={listRef} className="cm-stepper" aria-label="Các bước">
    {STEPS.map(([label, icon], index) => <li key={label} className={index === step ? "is-on" : index < step ? "is-done" : ""}>
      <button type="button" disabled={!reachable(index)} aria-current={index === step ? "step" : undefined} onClick={() => onStep(index)}>
        <span className="cm-stepper__dot">{index < step ? <md-icon>check</md-icon> : index + 1}</span>
        <span className="cm-stepper__label"><md-icon>{icon}</md-icon>{label}</span>
      </button>
    </li>)}
  </ol>;
}

// `overview`: the names and overviews of a menu and its sub-menus (featureId = the menu, "" = every menu), written from
// what the features below already say; otherwise one feature's flows, name and overview.
export function AiDialog({ featureId, featureName, overview = false, startStep = 0, onClose, onExported, onImported, notify }) {
  const [step, setStep] = useState(startStep);
  const [flags, setFlags] = useState({ instructions: true, code: true, locked: true });
  const [pack, setPack] = useState(null);
  const [exportWanted, setExportWanted] = useState(startStep === 0);
  const [text, setText] = useState("");
  const [check, setCheck] = useState(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const preview = useRef(null);
  const fileInput = useRef(null);
  const pasteArea = useRef(null);
  const stepper = useRef(null);

  // Each export is recorded (the import checks the file belongs to it), so it is made only when step 1 is shown.
  useEffect(() => {
    if (!exportWanted) return undefined;
    let live = true;
    setError(""); setPack(null);
    const wanted = Object.fromEntries(Object.entries(flags).map(([key, value]) => [key, value ? "1" : "0"]));
    (overview ? businessApi.exportOverview(featureId, { instructions: wanted.instructions }) : businessApi.exportPack(featureId, wanted))
      .then((body) => { if (live) { setPack(body); onExported?.(); } })
      .catch((reason) => { if (live) setError(reason.message); });
    return () => { live = false; };
  }, [featureId, flags, exportWanted]); // eslint-disable-line react-hooks/exhaustive-deps

  // A new step starts at the top (the dialog keeps the previous step's scroll position otherwise).
  useEffect(() => {
    stepper.current?.scrollIntoView({ block: "start" });
    if (step === 1) setTimeout(() => pasteArea.current?.focus({ preventScroll: true }), 50);
  }, [step]);

  function go(index) {
    setError("");
    if (index === 0) setExportWanted(true);
    setStep(index);
  }

  async function copy() {
    if (await copyText(pack.text, preview.current)) { notify("Đã sao chép. Dán vào AI, rồi dán kết quả AI trả về vào đây."); go(1); }
    else notify("Đã chọn nội dung, nhấn Ctrl+C để sao chép");
  }
  function download() {
    downloadText(pack.filename, pack.text);
    notify("Đã tải file. Đính kèm vào AI, rồi dán kết quả AI trả về vào đây.");
    go(1);
  }

  async function runCheck() {
    setBusy(true); setError("");
    try { setCheck(await (overview ? businessApi.checkOverview : businessApi.checkImport)(featureId, text)); setStep(2); }
    catch (reason) { setError(reason.message); setCheck(null); }
    finally { setBusy(false); }
  }
  async function apply(close) {
    setBusy(true); setError("");
    try {
      const result = await (overview ? businessApi.applyOverview : businessApi.applyImport)(featureId, text);
      onImported?.(result.tree);
      if (overview) { notify(`Đã nhập tên và tổng quan của ${result.applied.items} menu (AI viết)`); close(); return; }
      const links = result.applied.links ? `, ${result.applied.links} liên kết` : "";
      const notes = result.applied.notes ? `, ${result.applied.notes} ghi chú` : "";
      notify(`Đã nhập ${result.applied.parts} phần (AI viết)${links}${notes}`);
      close();
    } catch (reason) {
      setError(reason.message);
    } finally {
      setBusy(false);
    }
  }
  function readFile(file) {
    if (!file) return;
    const reader = new FileReader();
    reader.onload = () => { setText(String(reader.result)); setCheck(null); };
    reader.readAsText(file);
  }

  const actions = (close) => {
    if (step === 0) return <>
      <Button onClick={close}>Đóng</Button>
      <Button variant="outlined" icon="content_copy" disabled={!pack} onClick={copy}>Sao chép</Button>
      <Button variant="outlined" icon="download" disabled={!pack} onClick={download}>Tải file</Button>
      <Button variant="filled" icon="arrow_forward" trailingIcon onClick={() => go(1)}>Tiếp: dán kết quả</Button>
    </>;
    if (step === 1) return <>
      <Button icon="arrow_back" onClick={() => go(0)}>Quay lại xuất</Button>
      <Button variant="filled" icon="fact_check" disabled={busy || !text.trim()} onClick={runCheck}>Kiểm tra</Button>
    </>;
    return <>
      <Button icon="arrow_back" onClick={() => go(1)}>Sửa nội dung</Button>
      <Button variant="filled" icon="upload" disabled={busy || !check?.ok} onClick={() => apply(close)}>Nhập</Button>
    </>;
  };

  const options = overview ? OVERVIEW_OPTIONS : OPTIONS;
  return <Dialog headline={`${overview ? "Tổng quan menu bằng AI" : "Viết tài liệu bằng AI"} · ${featureName}`} icon="auto_awesome" onClose={onClose} actions={actions} wide className="cm-dialog--ai">
    <Stepper listRef={stepper} step={step} onStep={go} reachable={(index) => index < 2 || Boolean(check)} />
    {step === 0 ? <>
      {overview ? <p>Một file nhỏ cho AI: các menu con, tên và tổng quan đã có của từng tính năng cùng tên các luồng (không kèm code). AI viết tên nghiệp vụ và tổng quan cho từng menu, từ menu sâu nhất lên. Tính năng chưa có tổng quan thì nên xuất tính năng đó cho AI trước.</p>
        : <p>Một file cho AI: hướng dẫn, dữ liệu của tính năng (thứ tự gọi của từng luồng, node, cạnh, đoạn code, điều kiện) và khối YAML là định dạng trả về. AI không cần truy cập code hay graph.</p>}
      {pack && overview ? <div className="cm-stats cm-stats--4">
        <div><b>{pack.stats.menus}</b><span>menu</span></div><div><b>{pack.stats.to_write}</b><span>menu AI viết</span></div>
        <div><b>{pack.stats.features}</b><span>tính năng</span></div><div><b>{pack.stats.features_without_overview}</b><span>tính năng chưa có tổng quan</span></div>
      </div> : pack ? <div className="cm-stats cm-stats--4">
        <div><b>{pack.stats.nodes}</b><span>node</span></div><div><b>{pack.stats.edges}</b><span>cạnh</span></div>
        <div><b>{pack.stats.evidence}</b><span>đoạn code</span></div><div><b>{pack.stats.locked}</b><span>phần khoá</span></div>
      </div> : <md-linear-progress indeterminate />}
      <div className="cm-opts">
        {options.map(([key, label, hint]) => <Checkbox key={key} checked={flags[key]} label={label} supporting={hint}
          onChange={(checked) => setFlags({ ...flags, [key]: checked })} />)}
      </div>
      <label className="cm-code-field"><span className="cm-label">Xem trước{pack ? ` · ${pack.filename}` : ""}</span>
        <textarea ref={preview} className="cm-code" rows={16} readOnly value={pack?.text || "Đang tạo file…"} spellCheck={false} /></label>
      <p className="md-muted cm-small">Sao chép hoặc tải file rồi đưa cho AI (ChatGPT, Claude, Copilot…), không cần viết thêm câu lệnh. Xong bước này sẽ tự chuyển sang bước dán kết quả.</p>
    </> : null}
    {step === 1 ? <>
      <p>Dán khối YAML AI trả về, hoặc chọn file AI đã tạo. Phần người đã sửa được giữ nguyên.</p>
      <span><Button variant="tonal" icon="attach_file" onClick={() => fileInput.current?.click()}>Chọn file</Button>
        <input ref={fileInput} type="file" accept=".yaml,.yml,.md,.txt" hidden onChange={(event) => readFile(event.target.files[0])} /></span>
      <textarea ref={pasteArea} className="cm-code" rows={22} value={text} spellCheck={false} aria-label="Nội dung AI trả về"
        placeholder={overview ? "export:\n  id: ovr-…\nitems:\n  - id: menu:…" : "export:\n  id: exp-…\nflows:\n  - id: flow:…"} onChange={(event) => { setText(event.target.value); setCheck(null); }} />
    </> : null}
    {step === 2 && check ? <>
      <p>{check.ok ? "File hợp lệ. Bấm Nhập để lưu; nội dung mới được dùng ngay, ghi là “AI viết”." : "File chưa nhập được. Sửa nội dung rồi kiểm tra lại."}</p>
      <ul className="cm-checks">{check.lines.map((line, index) => <li key={index} className={`cm-checks--${line.level}`}>
        <md-icon>{CHECK_ICONS[line.level] || "info"}</md-icon>{line.message}</li>)}</ul>
    </> : null}
    {busy ? <md-linear-progress indeterminate /> : null}
    {error ? <ErrorBanner>{error}</ErrorBanner> : null}
  </Dialog>;
}
