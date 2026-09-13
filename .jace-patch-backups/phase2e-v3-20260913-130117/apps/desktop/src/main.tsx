import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import { DetachedPanelApp } from "./shell/DetachedPanelApp";
import { readWindowEntry } from "./shell/windowEntry";
import "./styles.css";
import { applyStoredDesktopWindowMode } from "./shell/desktopWindowMode";
import {
  restoreCurrentWindowGeometry,
  startCurrentWindowGeometryTracking,
} from "./shell/windowLayout";

const entry = readWindowEntry();

// JACE_DESKTOP_WINDOWS_PHASE_2C
// JACE_DESKTOP_WINDOWS_PHASE_2D

const content =
  entry.panel === "core" || entry.panel === "office" ? (
    <DetachedPanelApp panel={entry.panel} />
  ) : (
    <App detachedWorkspace={entry.panel === "workspace"} />
  );

async function startJaceDesktop() {
  await applyStoredDesktopWindowMode();
  await restoreCurrentWindowGeometry();

  ReactDOM.createRoot(
    document.getElementById("root") as HTMLElement,
  ).render(
    <React.StrictMode>{content}</React.StrictMode>,
  );

  void startCurrentWindowGeometryTracking();
}

void startJaceDesktop();
