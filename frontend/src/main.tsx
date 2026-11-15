import './components/krita-editor.css';
import React from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App";
import "./theme.css";
import "./premium.css";
// Stage 1: shared tokens and shell primitives. Existing page layouts are preserved.
import "./design-system.css";
// Phase 2: focused assistant + code workspace layouts.
import "./stage2-workspaces.css";
import "./model-inventory.css";
import "./system-preferences.css";
import "./image-studio.css";
import "./audio-workspace.css";

createRoot(document.getElementById("root")!).render(<React.StrictMode><App /></React.StrictMode>);
