import React, { useEffect, useState } from "react";
import { Button, ErrorBanner, Loading, Select, TextField } from "../../md/react.jsx";
import { http } from "../../app/http.js";

const PRESET_EXAMPLES = {
  // F-Search
  search_documents: { query: "auth", limit: 5 },
  read_document: { id: "1", query: "auth" },
  // CSV
  csv_list: { query: "" },
  csv_search: { id: "demo", limit: 10, filters: [] },
  // Monitor
  monitor_errors: { hours: 24, limit: 10 },
  monitor_tools: { hours: 24, server: "csv" },
  monitor_status: {},
  // Code map
  codemap_search: { question: "login", detail: "normal" },
  codemap_impact: { target: "users", detail: "normal" },
  codemap_trace_flow: { entry: "POST /login", detail: "normal" },
  codemap_file_context: { path: "README.md" },
  codemap_current_behavior: { topic: "auth", detail: "normal" },
  codemap_check_terms: { text: "user login authentication" },
  codemap_status: { detail: "normal" },
  // SVN
  svn_repos: {},
  svn_branches: { repo: "repo1" },
  svn_list: { repo: "repo1", path: "trunk" },
  svn_read: { repo: "repo1", path: "trunk/README.md" },
  svn_log: { repo: "repo1", path: "trunk", limit: 5 },
  svn_diff: { repo: "repo1", path: "trunk" },
  // Box Workspace
  box_list_files: { path: "", limit: 20 },
  box_read_file: { path: "README.md" },
  // API Specs
  api_list: {},
  api_describe: { set: "orders" },
  api_schema: { set: "orders" },
};

function extractExampleFromDesc(desc) {
  if (!desc || typeof desc !== "string") return null;
  const match = desc.match(/e\.g\.?\s*['"]([^'"]+)['"]/i) || desc.match(/vd:?\s*['"]([^'"]+)['"]/i);
  return match ? match[1] : null;
}

function buildSmartSample(tool) {
  if (!tool) return {};
  if (PRESET_EXAMPLES[tool.name]) {
    return PRESET_EXAMPLES[tool.name];
  }
  const schema = tool.inputSchema || {};
  const props = schema.properties || {};
  const sample = {};

  for (const [key, prop] of Object.entries(props)) {
    if (prop.default !== undefined) {
      sample[key] = prop.default;
    } else if (prop.enum && prop.enum.length) {
      sample[key] = prop.enum[0];
    } else if (prop.type === "string") {
      const fromDesc = extractExampleFromDesc(prop.description);
      if (fromDesc) {
        sample[key] = fromDesc;
      } else if (key === "question") {
        sample[key] = "login";
      } else if (key === "query" || key === "q" || key === "text" || key === "topic" || key === "target") {
        sample[key] = "auth";
      } else if (key === "entry") {
        sample[key] = "POST /api/login";
      } else if (key === "id" || key.endsWith("_id")) {
        sample[key] = "sample_id";
      } else if (key === "path" || key === "file") {
        sample[key] = "README.md";
      } else if (key.includes("date")) {
        sample[key] = "2026-01-01";
      } else {
        sample[key] = "sample_val";
      }
    } else if (prop.type === "number" || prop.type === "integer") {
      if (key === "limit") sample[key] = 10;
      else if (key === "hours") sample[key] = 24;
      else if (prop.minimum !== undefined) sample[key] = prop.minimum;
      else sample[key] = 1;
    } else if (prop.type === "boolean") {
      sample[key] = false;
    } else if (prop.type === "array") {
      if (prop.items?.type === "object") {
        sample[key] = [buildSmartSample({ name: "", inputSchema: prop.items })];
      } else if (prop.items?.type === "string") {
        sample[key] = ["sample_item"];
      } else {
        sample[key] = [];
      }
    } else if (prop.type === "object") {
      sample[key] = buildSmartSample({ name: "", inputSchema: prop });
    } else {
      sample[key] = "";
    }
  }
  return sample;
}

export default function Tester() {
  const [servers, setServers] = useState([]);
  const [serverPath, setServerPath] = useState("");
  const [tools, setTools] = useState([]);
  const [selectedToolName, setSelectedToolName] = useState("");
  const [argsText, setArgsText] = useState("{}");
  const [loadingTools, setLoadingTools] = useState(false);
  const [running, setRunning] = useState(false);
  const [response, setResponse] = useState(null);
  const [error, setError] = useState(null);

  // Load available MCP servers
  useEffect(() => {
    http.get("/monitor/api/mcp/servers").then((res) => {
      const list = res.servers || [];
      setServers(list);
      if (list.length) setServerPath(list[0].path);
    }).catch((err) => setError(err.message));
  }, []);

  // When selected server changes, discover tools via tools/list
  const loadTools = (path) => {
    if (!path) return;
    setLoadingTools(true);
    setTools([]);
    setSelectedToolName("");
    setResponse(null);
    setError(null);
    http.post("/monitor/api/mcp/invoke", { path, method: "tools/list" })
      .then((res) => {
        if (!res.ok && res.raw_response?.error) {
          setError(res.raw_response.error.message || `Lỗi MCP ${res.status_code}`);
          return;
        }
        const toolList = res.raw_response?.result?.tools || [];
        setTools(toolList);
        if (toolList.length) {
          const first = toolList[0];
          setSelectedToolName(first.name);
          setArgsText(JSON.stringify(buildSmartSample(first), null, 2));
        } else {
          setArgsText("{}");
        }
      })
      .catch((err) => setError(err.message))
      .finally(() => setLoadingTools(false));
  };

  useEffect(() => {
    loadTools(serverPath);
  }, [serverPath]);

  // When tool selection changes
  const onSelectTool = (name) => {
    setSelectedToolName(name);
    setResponse(null);
    const found = tools.find((t) => t.name === name);
    if (found) {
      setArgsText(JSON.stringify(buildSmartSample(found), null, 2));
    }
  };

  const currentTool = tools.find((t) => t.name === selectedToolName);

  const loadSample = () => {
    if (currentTool) {
      setArgsText(JSON.stringify(buildSmartSample(currentTool), null, 2));
      window.md?.snackbar("Đã nạp mẫu tham số có sẵn");
    }
  };

  const runTool = async () => {
    let parsedArgs = {};
    try {
      parsedArgs = JSON.parse(argsText || "{}");
    } catch (e) {
      window.md?.snackbar(`Lỗi cú pháp JSON tham số: ${e.message}`);
      return;
    }

    setRunning(true);
    setResponse(null);
    try {
      const res = await http.post("/monitor/api/mcp/invoke", {
        path: serverPath,
        method: "tools/call",
        params: {
          name: selectedToolName,
          arguments: parsedArgs,
        },
      });
      setResponse(res);
    } catch (e) {
      window.md?.snackbar(`Lỗi gọi tool: ${e.message}`);
      setResponse({
        ok: false,
        status_code: 500,
        latency_ms: 0,
        raw_response: { error: { message: e.message } },
      });
    } finally {
      setRunning(false);
    }
  };

  const copyText = (txt) => {
    navigator.clipboard.writeText(txt);
    window.md?.snackbar("Đã sao chép vào bộ nhớ tạm");
  };

  const properties = currentTool?.inputSchema?.properties || {};
  const requiredSet = new Set(currentTool?.inputSchema?.required || []);

  return (
    <div className="md-stack mo-tester" style={{ gap: 20, marginTop: 12 }}>
      {error ? <ErrorBanner>{error}</ErrorBanner> : null}

      <div className="md-grid" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(360px, 1fr))", gap: 16 }}>
        {/* Left column: Server & Tool picker & Input parameters */}
        <div className="md-card md-card--outlined" style={{ padding: 18, display: "flex", flexDirection: "column", gap: 14 }}>
          <h2 className="md-title-medium" style={{ margin: 0, display: "flex", alignItems: "center", gap: 8 }}>
            <md-icon style={{ color: "var(--md-sys-color-primary)" }}>tune</md-icon>Chọn Server & Tool
          </h2>

          <Select
            label="MCP Server"
            value={serverPath}
            onChange={setServerPath}
            options={servers.map((s) => [s.path, `${s.label} (${s.command}) · ${s.path}`])}
          />

          {loadingTools ? (
            <Loading inline>Đang khám phá danh sách tools…</Loading>
          ) : tools.length ? (
            <Select
              label="Tool cần test"
              value={selectedToolName}
              onChange={onSelectTool}
              options={tools.map((t) => [t.name, `${t.name}${t.description ? ` — ${t.description.slice(0, 45)}…` : ""}`])}
            />
          ) : (
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
              <p className="md-muted md-body-small" style={{ margin: 0 }}>Server này không trả về tool nào.</p>
              <md-text-button onClick={() => loadTools(serverPath)}>
                <md-icon slot="icon">refresh</md-icon>Thử lại
              </md-text-button>
            </div>
          )}

          {currentTool ? (
            <div style={{ background: "var(--md-sys-color-surface-container)", padding: "10px 14px", borderRadius: 8 }}>
              <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
                <strong style={{ fontSize: 13, color: "var(--md-sys-color-primary)" }}>{currentTool.name}</strong>
                {currentTool.annotations?.readOnlyHint ? (
                  <span className="md-badge" style={{ fontSize: 11, height: 20 }}>read-only</span>
                ) : null}
              </div>
              <p style={{ margin: "6px 0 0", fontSize: 13, color: "var(--md-sys-color-on-surface-variant)", lineHeight: 1.5 }}>
                {currentTool.description || "Không có mô tả"}
              </p>
            </div>
          ) : null}

          {/* Argument controls */}
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginTop: 4 }}>
            <strong style={{ fontSize: 13 }}>Tham số (arguments JSON):</strong>
            <div style={{ display: "flex", gap: 6 }}>
              {currentTool ? (
                <md-text-button onClick={loadSample}>
                  <md-icon slot="icon">auto_fix_high</md-icon>Nạp mẫu có sẵn
                </md-text-button>
              ) : null}
              <md-text-button onClick={() => setArgsText("{}")}>
                <md-icon slot="icon">clear_all</md-icon>Xoá {}
              </md-text-button>
            </div>
          </div>

          <TextField
            type="textarea"
            rows={8}
            value={argsText}
            onChange={setArgsText}
            style={{ fontFamily: "var(--md-ref-typeface-mono)", fontSize: 13 }}
            supportingText="JSON arguments truyền vào tool (tự động load mẫu khi chọn tool)"
          />

          {/* Schema Properties helper table */}
          {Object.keys(properties).length > 0 ? (
            <div style={{ borderTop: "1px solid var(--md-sys-color-outline-variant)", paddingTop: 10 }}>
              <p style={{ margin: "0 0 8px", fontSize: 12, fontWeight: 600, color: "var(--md-sys-color-on-surface-variant)" }}>
                Các trường tham số theo Schema:
              </p>
              <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
                {Object.entries(properties).map(([pName, pMeta]) => (
                  <button
                    key={pName}
                    type="button"
                    style={{
                      border: "1px solid var(--md-sys-color-outline-variant)",
                      borderRadius: 6,
                      background: "var(--md-sys-color-surface-container-low)",
                      padding: "4px 8px",
                      fontSize: 12,
                      cursor: "pointer",
                      display: "inline-flex",
                      alignItems: "center",
                      gap: 4,
                      color: "var(--md-sys-color-on-surface)",
                    }}
                    title={`${pMeta.description || ""} (${pMeta.type || "any"})`}
                    onClick={() => {
                      try {
                        const cur = JSON.parse(argsText || "{}");
                        if (!(pName in cur)) {
                          cur[pName] = pMeta.default !== undefined ? pMeta.default : (pMeta.type === "string" ? "sample" : 0);
                          setArgsText(JSON.stringify(cur, null, 2));
                        }
                      } catch {
                        /* ignore */
                      }
                    }}
                  >
                    <code>{pName}</code>
                    <span style={{ fontSize: 10, opacity: 0.7 }}>{pMeta.type}</span>
                    {requiredSet.has(pName) ? <span style={{ color: "var(--md-sys-color-error)", fontSize: 11 }}>*</span> : null}
                  </button>
                ))}
              </div>
            </div>
          ) : null}

          <div style={{ display: "flex", gap: 12, marginTop: 6 }}>
            <md-filled-button disabled={running || !selectedToolName || undefined} onClick={runTool} style={{ flex: 1 }}>
              {running ? (
                <md-circular-progress indeterminate style={{ width: 16, height: 16 }} slot="icon" />
              ) : (
                <md-icon slot="icon">play_arrow</md-icon>
              )}
              {running ? "Đang gửi JSON-RPC…" : "Chạy thử tool (Run)"}
            </md-filled-button>
          </div>
        </div>

        {/* Right column: Execution results */}
        <div className="md-card md-card--outlined" style={{ padding: 18, display: "flex", flexDirection: "column", gap: 14 }}>
          <h2 className="md-title-medium" style={{ margin: 0, display: "flex", alignItems: "center", gap: 8 }}>
            <md-icon style={{ color: "var(--md-sys-color-primary)" }}>terminal</md-icon>Kết quả phản hồi (Response)
          </h2>

          {running ? (
            <Loading>Đang thực thi tools/call và chờ kết quả từ MCP server…</Loading>
          ) : response ? (
            <div className="md-stack" style={{ gap: 12 }}>
              <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
                <span className={`md-badge ${response.ok ? "md-badge--primary" : "md-badge--error"}`} style={{ height: 26, padding: "0 10px", fontSize: 12, fontWeight: 600 }}>
                  <md-icon style={{ "--md-icon-size": "16px" }}>{response.ok ? "check_circle" : "error"}</md-icon>
                  {response.status_code} {response.ok ? "Thành công" : "Lỗi"}
                </span>
                <span className="md-badge" style={{ height: 26, padding: "0 10px", fontSize: 12 }}>
                  <md-icon style={{ "--md-icon-size": "16px" }}>timer</md-icon>
                  {response.latency_ms} ms
                </span>
              </div>

              {/* Rendered output */}
              <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
                <strong style={{ fontSize: 13 }}>Nội dung kết quả:</strong>
                <md-icon-button
                  title="Sao chép kết quả"
                  onClick={() => copyText(JSON.stringify(response.raw_response?.result || response.raw_response, null, 2))}
                >
                  <md-icon>content_copy</md-icon>
                </md-icon-button>
              </div>

              <div
                style={{
                  background: "var(--md-sys-color-surface-container)",
                  border: "1px solid var(--md-sys-color-outline-variant)",
                  borderRadius: 8,
                  padding: "12px 16px",
                  maxHeight: 360,
                  overflow: "auto",
                  fontFamily: "var(--md-ref-typeface-mono)",
                  fontSize: 12.5,
                  lineHeight: 1.6,
                  whiteSpace: "pre-wrap",
                }}
              >
                {(() => {
                  const res = response.raw_response?.result;
                  if (res?.content && Array.isArray(res.content)) {
                    return res.content.map((c) => c.text || JSON.stringify(c, null, 2)).join("\n");
                  }
                  if (response.raw_response?.error) {
                    return `Lỗi JSON-RPC: ${response.raw_response.error.message || JSON.stringify(response.raw_response.error)}`;
                  }
                  return JSON.stringify(response.raw_response, null, 2);
                })()}
              </div>

              {/* Raw JSON-RPC Toggle */}
              <details style={{ marginTop: 8 }}>
                <summary style={{ cursor: "pointer", fontSize: 13, color: "var(--md-sys-color-primary)", fontWeight: 500 }}>
                  Xem chi tiết gói tin JSON-RPC
                </summary>
                <div style={{ marginTop: 8 }}>
                  <p style={{ margin: "4px 0", fontSize: 12, fontWeight: 600 }}>Request:</p>
                  <pre style={{ background: "var(--md-sys-color-surface-container-low)", padding: 8, borderRadius: 6, fontSize: 11, overflow: "auto" }}>
                    {JSON.stringify(response.raw_request, null, 2)}
                  </pre>
                  <p style={{ margin: "4px 0", fontSize: 12, fontWeight: 600 }}>Raw Response:</p>
                  <pre style={{ background: "var(--md-sys-color-surface-container-low)", padding: 8, borderRadius: 6, fontSize: 11, overflow: "auto" }}>
                    {JSON.stringify(response.raw_response, null, 2)}
                  </pre>
                </div>
              </details>
            </div>
          ) : (
            <div style={{ padding: "50px 0", textAlign: "center", color: "var(--md-sys-color-on-surface-variant)" }}>
              <md-icon style={{ "--md-icon-size": "42px", opacity: 0.4 }}>science</md-icon>
              <p style={{ margin: "8px 0 0", fontSize: 13.5 }}>Tham số mẫu đã được tự động nạp. Bấm <b>"Chạy thử tool (Run)"</b> để kiểm tra.</p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
