import { Suspense, lazy } from "react";
import { NavLink, Route, Routes } from "react-router-dom";

// Route-level code splitting: the math fixture page carries KaTeX (+ its
// font CSS), which does not belong in the entry chunk of an operator
// console.
const NotebooksPage = lazy(() =>
  import("./pages/NotebooksPage").then((m) => ({ default: m.NotebooksPage })),
);
const NotebookDetailPage = lazy(() =>
  import("./pages/notebook/DetailPage").then((m) => ({
    default: m.NotebookDetailPage,
  })),
);
const MathFixturePage = lazy(() =>
  import("./pages/MathFixturePage").then((m) => ({
    default: m.MathFixturePage,
  })),
);
// Observability surfaces (arx-b3, brief §7.4): one lazy chunk each —
// the densest telemetry tier never rides the entry chunk.
const LogsPage = lazy(() =>
  import("./pages/observability/LogsPage").then((m) => ({
    default: m.LogsPage,
  })),
);
const RequestsPage = lazy(() =>
  import("./pages/observability/RequestsPage").then((m) => ({
    default: m.RequestsPage,
  })),
);
const ConnectionsPage = lazy(() =>
  import("./pages/observability/ConnectionsPage").then((m) => ({
    default: m.ConnectionsPage,
  })),
);
// Capability config + graph views (arx-b3, brief §7.5/§7.6): lazy
// chunks; the graph page itself lazy-loads the 3-D module only on
// operator activation (AC-B.22).
const CapabilitiesPage = lazy(() =>
  import("./pages/capabilities/CapabilitiesPage").then((m) => ({
    default: m.CapabilitiesPage,
  })),
);
const GraphPage = lazy(() =>
  import("./pages/graph/GraphPage").then((m) => ({
    default: m.GraphPage,
  })),
);

/**
 * App shell [C]: quiet chrome voice, domain nouns only (CP-1).
 * Skip-link + focusable main carry the shipped console's a11y floor.
 */
export function App() {
  return (
    <>
      <a href="#main" className="skip-link">
        Skip to content
      </a>
      <header className="shell-header">
        <h1 style={{ fontSize: "var(--scale-2)" }}>arXMCP</h1>
        <nav aria-label="Primary">
          <NavLink to="/">Notebooks</NavLink>
          <NavLink to="/logs">Logs</NavLink>
          <NavLink to="/requests">Requests</NavLink>
          <NavLink to="/connections">Connections</NavLink>
          <NavLink to="/capabilities">Capabilities</NavLink>
        </nav>
      </header>
      <main id="main" tabIndex={-1} className="shell-main">
        <Suspense fallback={<p className="reg-telemetry">Loading…</p>}>
          <Routes>
            <Route path="/" element={<NotebooksPage />} />
            <Route path="/notebooks/:slug" element={<NotebookDetailPage />} />
            <Route path="/notebooks/:slug/graph" element={<GraphPage />} />
            <Route path="/logs" element={<LogsPage />} />
            <Route path="/capabilities" element={<CapabilitiesPage />} />
            <Route path="/requests" element={<RequestsPage />} />
            <Route path="/connections" element={<ConnectionsPage />} />
            <Route path="/specimen/math" element={<MathFixturePage />} />
          </Routes>
        </Suspense>
      </main>
    </>
  );
}
