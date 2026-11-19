// User guide (/help): HTML the server renders from its own guide files (help/parts + each module's GUIDE.md),
// never from user content, so it is inserted as HTML.
import React from "react";
import { useTitle } from "../context.jsx";
import { http } from "../http.js";
import { Button } from "../../md/react.jsx";
import { Skeleton, useLoad } from "../ui.jsx";

// Copilot setup: the mcp.json block (address taken now, so the current port) and one skill per MCP server.
function CopilotSetup() {
  const copy = async () => {
    try {
      const config = await http.get("/api/mcp/config");
      await navigator.clipboard.writeText(JSON.stringify(config, null, 2));
      window.md?.snackbar("Đã sao chép cấu hình MCP. Dán vào .vscode/mcp.json");
    } catch (error) {
      window.md?.snackbar(error.message || "Không sao chép được");
    }
  };
  return <div className="md-card md-card--outlined" style={{ padding: 16, marginBottom: 16 }}>
    <strong>Dùng với GitHub Copilot</strong>
    <p style={{ margin: "4px 0 12px" }}>Sao chép cấu hình MCP (dán vào <code>.vscode/mcp.json</code>), tải skills
      (giải nén vào <code>.github/skills/</code> của folder). Đổi cổng thì sao chép lại.</p>
    <div className="md-row">
      <Button variant="filled" icon="content_copy" onClick={copy}>Sao chép cấu hình MCP</Button>
      <Button variant="tonal" icon="download" onClick={() => { window.location.href = "/api/mcp/skills.zip"; }}>Tải skills (.zip)</Button>
    </div>
  </div>;
}

export default function Help() {
  const { data } = useLoad(() => http.get("/api/help"));
  const { data: mcp } = useLoad(() => http.get("/api/mcp"));
  useTitle(data?.title || "Hướng dẫn sử dụng");
  return <>
    {mcp?.servers?.length ? <CopilotSetup /> : null}
    {data ? <div className="md-help">
      <nav className="md-help__toc md-card md-card--outlined" aria-label="Mục lục" dangerouslySetInnerHTML={{ __html: data.toc }} />
      <article className="md-help__body" dangerouslySetInnerHTML={{ __html: data.html }} />
    </div> : <div className="md-help">
      <nav className="md-help__toc md-card md-card--outlined" style={{ padding: 16 }}><Skeleton count={6} /></nav>
      <article className="md-help__body" style={{ padding: 16 }}><Skeleton count={12} /></article>
    </div>}
  </>;
}
