import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import { DetachedPanelApp } from "./shell/DetachedPanelApp";
import { readWindowEntry } from "./shell/windowEntry";
import "./styles.css";

const entry = readWindowEntry();

const content =
  entry.panel === "core" || entry.panel === "office" ? (
    <DetachedPanelApp panel={entry.panel} />
  ) : (
    <App detachedWorkspace={entry.panel === "workspace"} />
  );

ReactDOM.createRoot(document.getElementById("root") as HTMLElement).render(
  <React.StrictMode>{content}</React.StrictMode>,
);
