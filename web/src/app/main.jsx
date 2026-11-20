// Viewer Hub single-page app. The server answers every page URL with templates/app.html, which loads this file;
// the menu and what this build contains come from GET /api/app (app/portal.py).
import React, { useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import { http } from "./http.js";
import { Router } from "./router.jsx";
import Shell from "./Shell.jsx";
import "./app.css";

function App() {
  const [app, setApp] = useState(null);
  const [error, setError] = useState(null);
  const load = () => http.get("/api/app").then(setApp, setError);
  useEffect(() => { load(); }, []);
  if (error) return <div className="md-empty"><md-icon>cloud_off</md-icon><h2>Không kết nối được Viewer Hub</h2><p>{error.message}</p></div>;
  if (!app) return <div className="md-loading" style={{ height: "100vh" }}><md-circular-progress indeterminate></md-circular-progress></div>;
  return <Router><Shell app={app} reload={load} /></Router>;
}

createRoot(document.getElementById("app")).render(<React.StrictMode><App /></React.StrictMode>);
