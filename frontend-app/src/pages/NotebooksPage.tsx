/**
 * Notebook index (brief §7.1): rule-separated rows, NOT a card grid —
 * name in the editorial register, machine facts as telemetry chips.
 * Consumes the typed client against /api/v1/notebooks (IF-1).
 *
 * States designed live/empty/error (§7): empty teaches the action;
 * error names the failing dependency. The status line is a MOUNTED
 * aria-live region whose text updates (never remounted).
 */
import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { useApi } from "../api/ApiProvider";
import type { NotebookRow, PageEnvelope } from "../api/types";
import { enterFadeUp } from "../motion/anime";
import { CreateNotebookForm } from "./CreateNotebookForm";

type LoadState =
  | { phase: "loading" }
  | { phase: "loaded"; page: PageEnvelope<NotebookRow> }
  | { phase: "error"; detail: string };

export function NotebooksPage() {
  const api = useApi();
  const [state, setState] = useState<LoadState>({ phase: "loading" });
  const [reloadKey, setReloadKey] = useState(0);
  const [justCreated, setJustCreated] = useState<string | null>(null);

  const onCreated = useCallback((slug: string) => {
    setJustCreated(slug);
    setReloadKey((k) => k + 1);
  }, []);

  // Creation fade-up (brief §5.3-C): the freshly created row enters
  // with the 8px/200ms grammar; reduced-motion gated in the wrapper.
  const newRowRef = useCallback((el: HTMLLIElement | null) => {
    if (el !== null) void enterFadeUp(el);
  }, []);

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      const { data, error, response } = await api.GET("/api/v1/notebooks");
      if (cancelled) return;
      if (error !== undefined || data === undefined) {
        setState({
          phase: "error",
          detail: `GET /api/v1/notebooks failed (${response?.status ?? "network"}) — is the arXMCP server running on 127.0.0.1:7733?`,
        });
        return;
      }
      setState({ phase: "loaded", page: data as unknown as PageEnvelope<NotebookRow> });
    })();
    return () => {
      cancelled = true;
    };
  }, [api, reloadKey]);

  return (
    <section aria-labelledby="notebooks-h">
      <div className="section-header">
        <h2 id="notebooks-h">Notebooks</h2>
      </div>

      <p aria-live="polite" className="reg-telemetry" data-testid="notebooks-status">
        {state.phase === "loading" && "Loading notebooks…"}
        {state.phase === "loaded" &&
          `${state.page.total} notebook${state.page.total === 1 ? "" : "s"}`}
        {state.phase === "error" && state.detail}
      </p>

      {state.phase === "loaded" && state.page.items.length === 0 && (
        <div className="empty-state">
          <p>No notebooks yet.</p>
          <p>
            Create one with <code className="reg-telemetry">POST /api/v1/notebooks</code> or from
            the <a href="/ui/">fallback console</a>.
          </p>
        </div>
      )}

      {state.phase === "loaded" && state.page.items.length > 0 && (
        <ul className="notebook-list" data-testid="notebook-list">
          {state.page.items.map((nb) => (
            <li
              key={nb.slug}
              className="notebook-row"
              ref={nb.slug === justCreated ? newRowRef : undefined}
            >
              <div className="reg-editorial notebook-name">
                <Link to={`/notebooks/${nb.slug}`}>{nb.display_name || nb.slug}</Link>
              </div>
              {nb.description && <div className="reg-editorial notebook-desc">{nb.description}</div>}
              <div className="notebook-meta reg-telemetry">
                <span className="chip">{nb.slug}</span>
                <span className="chip">{nb.notebook_kind}</span>
                {nb.discovery_category && <span className="chip">{nb.discovery_category}</span>}
                <span className="chip">parse: {nb.parse_status}</span>
                <span className="notebook-created">{nb.created_at}</span>
              </div>
            </li>
          ))}
        </ul>
      )}

      <CreateNotebookForm onCreated={onCreated} />
    </section>
  );
}
