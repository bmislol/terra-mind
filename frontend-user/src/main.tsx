import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { App } from "./App";
import "./styles.css";
import { applyTheme, loadTheme } from "./theme";

// Apply the persisted theme before first paint (no flash of the wrong palette).
applyTheme(loadTheme());

const root = document.getElementById("root");
if (!root) throw new Error("#root not found");

createRoot(root).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
