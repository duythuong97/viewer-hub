// One dataset, the old csv-viewer flow: pick a source, filters (column · IN/== · value, all must match), Tìm kiếm,
// then the rows (visible columns, at most MAX_RESULTS). Cell values are always text, never HTML.
import React, { useRef, useState } from "react";
import { Dialog, IconButton, Select, TextField } from "../../md/react.jsx";
import { useApp, useLayout, useTitle } from "../../app/context.jsx";
import { http } from "../../app/http.js";
import { useRouter } from "../../app/router.jsx";
import { LinkButton, PageHeader, Skeleton, useAction, useLoad } from "../../app/ui.jsx";
import ColumnsDialog from "./ColumnsDialog.jsx";
import { API } from "./index.jsx";
import InfoDialog from "./InfoDialog.jsx";
import { uploadCsv } from "./ListPage.jsx";

const MAX_RESULTS = 500;
const OPERATORS = [["IN", "IN · chứa"], ["==", "== · bằng"]];

export default function DatasetPage({ id }) {
  const { data, error, reload } = useLoad(() => http.get(`${API}/${encodeURIComponent(id)}`), [id]);
  const list = useLoad(() => http.get(API), [id]);
  useTitle("CSV");
  useLayout("wide");  // many, long columns: use the whole width
  if (error) return <div className="md-empty"><md-icon>search_off</md-icon><h2>{error.message}</h2>
    <LinkButton to="/csv/?manage=1" icon="folder_managed">Quản lý bộ dữ liệu</LinkButton></div>;
  if (!data || !list.data) return <div style={{ padding: 24 }}><Skeleton count={6} /></div>;
  return <Dataset key={data.id} dataset={data} datasets={list.data.datasets} reload={() => { reload(); list.reload(); }} />;
}

function Dataset({ dataset, datasets, reload }) {
  const { app } = useApp();
  const { navigate } = useRouter();
  const columns = dataset.visible;
  const fresh = (preset = {}) => {
    const column = preset.column || columns[0]?.key;
    return { id: Math.random(), column, operator: preset.operator || columns.find((c) => c.key === column)?.op || "IN", value: preset.value || "", error: false };
  };
  const [filters, setFilters] = useState(() => (dataset.defaults.length ? dataset.defaults : [{}]).map(fresh));
  const [result, setResult] = useState(null);
  const [status, setStatus] = useState("Sẵn sàng.");
  const [loading, setLoading] = useState(false);
  const [isFetchingNextPage, setIsFetchingNextPage] = useState(false);
  const [last, setLast] = useState(null);
  const [dialog, setDialog] = useState(null);
  const [run] = useAction();
  const upload = useRef(null);
  const editable = !dataset.readonly;

  const change = (index, patch) => setFilters(filters.map((f, i) => (i === index ? { ...f, ...patch } : f)));
  const search = async () => {
    const empty = filters.some((f) => !f.value.trim());
    if (empty) {
      setFilters(filters.map((f) => ({ ...f, error: !f.value.trim() })));
      setStatus("Nhập giá trị cho mọi bộ lọc (hoặc xóa bộ lọc thừa).");
      return;
    }
    const rules = filters.map(({ column, operator, value }) => ({ column, operator, value: value.trim() }));
    setStatus("Đang tìm kiếm…");
    setLoading(true);
    try {
      const data = await http.get(`${API}/${encodeURIComponent(dataset.id)}/rows`, { filters: JSON.stringify(rules), limit: MAX_RESULTS, offset: 0 });
      setLast(rules);
      setResult(data);
      if (!data.rows.length) setStatus("Không tìm thấy dữ liệu.");
      else if (data.total > data.rows.length) setStatus(`${data.rows.length.toLocaleString()} / ${data.total.toLocaleString()} kết quả (đã giới hạn; dùng Xuất CSV để lấy hết).`);
      else setStatus(`${data.total.toLocaleString()} kết quả.`);
    } catch (error) {
      setStatus(`Lỗi: ${error.message}`);
    } finally {
      setLoading(false);
    }
  };

  const fetchNextPage = async () => {
    if (!result || isFetchingNextPage || result.rows.length >= result.total) return;
    setIsFetchingNextPage(true);
    try {
      const data = await http.get(`${API}/${encodeURIComponent(dataset.id)}/rows`, {
        filters: JSON.stringify(last || []),
        limit: MAX_RESULTS,
        offset: result.rows.length,
      });
      const newTotalShown = result.rows.length + data.rows.length;
      setResult((prev) => ({
        ...prev,
        rows: [...prev.rows, ...data.rows],
      }));
      if (newTotalShown >= result.total) {
        setStatus(`${result.total.toLocaleString()} kết quả.`);
      } else {
        setStatus(`${newTotalShown.toLocaleString()} / ${result.total.toLocaleString()} kết quả (dùng Xuất CSV để lấy hết).`);
      }
    } catch (error) {
      window.md?.snackbar(`Lỗi tải tiếp dữ liệu: ${error.message}`);
    } finally {
      setIsFetchingNextPage(false);
    }
  };
  const exportUrl = `${API}/${encodeURIComponent(dataset.id)}/export.csv${last ? `?${new URLSearchParams({ filters: JSON.stringify(last) })}` : ""}`;
  const facts = `${dataset.rows.toLocaleString()} dòng · ${dataset.columns} cột${dataset.readonly ? ` · Data pack · ${dataset.pack} · chỉ đọc` : ""}`;

  return <>
    {/* The source picker names the dataset, so the header carries only its facts and actions. */}
    <PageHeader subtitle={facts}>
      <IconButton icon="upload_file" label="Tải CSV lên" disabled={app.readonly} onClick={() => upload.current?.click()} />
      <IconButton icon="folder_managed" label="Quản lý bộ dữ liệu" onClick={() => navigate("/csv/?manage=1")} />
      <IconButton icon="download" label="Xuất kết quả ra CSV" onClick={() => { window.location.href = exportUrl; }} />
      {editable ? <>
        <IconButton icon="edit" label="Sửa tên, mô tả" disabled={app.readonly} onClick={() => setDialog("info")} />
        <IconButton icon="view_column" label="Cấu hình cột" disabled={app.readonly} onClick={() => setDialog("columns")} />
        <IconButton icon="delete" label="Xoá bộ dữ liệu" disabled={app.readonly} onClick={() => setDialog("delete")} />
      </> : null}
    </PageHeader>
    <input ref={upload} type="file" accept=".csv,.tsv,.txt,text/csv" multiple hidden onChange={async (e) => {
      const files = e.target.files;
      e.target.value = "";
      setLoading(true);
      const created = await uploadCsv(files);
      setLoading(false);
      if (created.length) navigate(`/csv/?manage=1`);
    }} />

    <div className="md-stack">
      <form className="md-card md-card--outlined csv-form" noValidate onSubmit={(e) => { e.preventDefault(); search(); }}>
        <div className="md-card__body">
          <Select label="Nguồn dữ liệu" className="csv-form__source" value={dataset.id}
            options={datasets.map((d) => [d.id, `${d.title}${d.readonly && d.pack ? ` · ${d.pack}` : ""} · ${d.rows.toLocaleString()} dòng`])}
            onChange={(value) => { if (value && value !== dataset.id) navigate(`/csv/${encodeURIComponent(value)}`); }} />
          {dataset.description ? <p className="csv-form__desc">{dataset.description}</p> : null}
          <div className="csv-filters" aria-label="Bộ lọc">
            {filters.map((filter, index) => <div key={filter.id} className="csv-filter">
              <Select label="Cột" className="csv-filter__column" value={filter.column}
                options={columns.map((c) => [c.key, c.label || c.name])}
                onChange={(column) => change(index, { column, operator: columns.find((c) => c.key === column)?.op || filter.operator })} />
              <Select label="Toán tử" className="csv-filter__operator" value={filter.operator} options={OPERATORS}
                onChange={(operator) => change(index, { operator })} />
              <FilterValue filter={filter} onChange={(value) => change(index, { value, error: false })} onEnter={search} />
              <IconButton icon="close" label="Xóa bộ lọc" className="csv-filter__remove" disabled={filters.length === 1}
                onClick={() => setFilters(filters.filter((_, i) => i !== index))} />
            </div>)}
          </div>
        </div>
        <div className="md-card__actions csv-form__actions">
          <md-text-button onClick={() => setFilters([...filters, fresh()])}><md-icon slot="icon">add</md-icon>Thêm bộ lọc</md-text-button>
          <span className="md-spacer"></span>
          <md-filled-button onClick={search}><md-icon slot="icon">search</md-icon>Tìm kiếm</md-filled-button>
        </div>
      </form>

      <div className="csv-result">
        <div className="csv-result__bar"><span role="status" aria-live="polite">{status}</span></div>
        {loading ? <md-linear-progress indeterminate style={{ width: "100%" }}></md-linear-progress> : null}
        {result && result.rows.length ? <div className="md-table-wrap">
          <table className="md-table csv-table">
            <thead><tr>{result.columns.map((c) => <th key={c.key} scope="col" className={c.type === "number" ? "md-table__num" : undefined}>{c.name}</th>)}</tr></thead>
            <tbody>{result.rows.map((row, r) => <tr key={r}>
              {row.map((value, i) => <td key={i} className={result.columns[i]?.type === "number" ? "md-table__num" : undefined}>{value ?? ""}</td>)}
            </tr>)}</tbody>
          </table>
        </div> : null}
        {isFetchingNextPage && <div className="vh-grid-loading-bar">Đang tải tiếp dữ liệu...</div>}
        {result && result.rows.length < result.total && !isFetchingNextPage ? (
          <div style={{ display: "flex", justifyContent: "center", padding: "12px 0" }}>
            <md-outlined-button onClick={fetchNextPage}>
              <md-icon slot="icon">expand_more</md-icon>
              Tải thêm dữ liệu ({result.rows.length.toLocaleString()} / {result.total.toLocaleString()})
            </md-outlined-button>
          </div>
        ) : null}
      </div>
    </div>

    {dialog === "info" ? <InfoDialog datasets={[dataset]} headline={`Sửa “${dataset.title}”`} icon="edit"
      onClose={() => setDialog(null)} onSaved={reload} /> : null}
    {dialog === "columns" ? <ColumnsDialog dataset={dataset} onClose={() => setDialog(null)} onSaved={reload} /> : null}
    {dialog === "delete" ? <Dialog className="md-dialog--danger" headline={`Xoá “${dataset.title}”?`} icon="delete" onClose={() => setDialog(null)}
      actions={(close) => <>
        <md-text-button onClick={close}>Huỷ</md-text-button>
        <md-filled-button class="md-button--danger" onClick={async () => {
          close();
          if (await run(() => http.delete(`${API}/${encodeURIComponent(dataset.id)}`), (r) => r.message)) navigate("/csv/", { replace: true });
        }}>Xoá</md-filled-button>
      </>}>
      File CSV và index trong thư mục dữ liệu sẽ bị xoá. Không hoàn tác được.
    </Dialog> : null}
  </>;
}

// Value field: Enter searches; shows "Nhập giá trị" when empty on search.
function FilterValue({ filter, onChange, onEnter }) {
  const ref = useRef(null);
  React.useEffect(() => {
    const field = ref.current?.querySelector("md-outlined-text-field");
    if (!field) return;
    field.error = filter.error;
    field.errorText = filter.error ? "Nhập giá trị" : "";
  }, [filter.error]);
  return <div ref={ref} className="csv-filter__value">
    <TextField label="Giá trị" placeholder="Nhập giá trị…" value={filter.value} onChange={onChange}
      onKeyDown={(e) => { if (e.key === "Enter" && !e.isComposing) { e.preventDefault(); onEnter(); } }} />
  </div>;
}
