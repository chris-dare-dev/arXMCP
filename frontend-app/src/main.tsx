import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import "./fonts";
import "./styles/tokens.css";
import "./styles/base.css";
import "./styles/observability.css";
import "./styles/capabilities.css";
import "./styles/graph.css";
import "./styles/shadcn-aliases.css";
import { App } from "./App";

const rootEl = document.getElementById("root");
if (rootEl === null) {
  throw new Error("index.html is missing #root");
}

createRoot(rootEl).render(
  <StrictMode>
    <BrowserRouter basename="/app">
      <App />
    </BrowserRouter>
  </StrictMode>,
);
