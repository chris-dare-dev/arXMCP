/**
 * Notebook detail (brief §7.1) — THE two-register screen: editorial
 * header (title, topic/description prose) over telemetry surfaces
 * (corpus stats, drift indicator, papers table), with the Tufte
 * margin-metadata channel on the right (LA-4: created, corpus v,
 * embedder, chunker, marker written, export affordance).
 *
 * Data: three parallel GETs against the typed client — the notebook
 * row (from the list; /api/v1 has no single-notebook GET by design),
 * the health report, the papers page. Health and papers degrade
 * independently; a missing notebook is a designed not-found state.
 */
import { useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useApi } from "../../api/ApiProvider";
import type {
  HealthResult,
  NotebookRow,
  PageEnvelope,
  PaperRow,
} from "../../api/types";
import { AddSourcePanel } from "./AddSourcePanel";
import { DangerZone } from "./DangerZone";
import { DiscoveryPanel } from "./DiscoveryPanel";
import { HealthPanel } from "./HealthPanel";
import { IngestPanel } from "./IngestPanel";
import { PapersTable } from "./PapersTable";
import { RenameControl } from "./RenameControl";
import { TopicEditor } from "./TopicEditor";

type DetailState =
  | { phase: "loading" }
  | { phase: "notfound" }
  | { phase: "error"; detail: string }
  | {
      phase: "loaded";
      notebook: NotebookRow;
      health: HealthResult | null;
      healthError: string | null;
      papers: PaperRow[];
      papersError: string | null;
    };

export function NotebookDetailPage() {
  const { slug = "" } = useParams();
  const api = useApi();
  const [state, setState] = useState<DetailState>({ phase: "loading" });
  const [reloadKey, setReloadKey] = useState(0);
  const reload = useCallback(() => setReloadKey((k) => k + 1), []);

  /** Local (optimistic) notebook-row patch — rename/topic apply here
   * immediately; a failed PATCH reverts through the same path. */
  const patchNotebook = useCallback((patch: Partial<NotebookRow>) => {
    setState((s) =>
      s.phase === "loaded" ? { ...s, notebook: { ...s.notebook, ...patch } } : s,
    );
  }, []);

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      const [nbRes, healthRes, papersRes] = await Promise.all([
        api.GET("/api/v1/notebooks", { params: { query: { limit: 500 } } }),
        api.GET("/api/v1/notebooks/{slug}/health", {
          params: { path: { slug } },
        }),
        api.GET("/api/v1/notebooks/{slug}/papers", {
          params: { path: { slug } },
        }),
      ]);
      if (cancelled) return;

      if (nbRes.error !== undefined || nbRes.data === undefined) {
        setState({
          phase: "error",
          detail: `GET /api/v1/notebooks failed (${nbRes.response?.status ?? "network"}) — is the arXMCP server running on 127.0.0.1:7733?`,
        });
        return;
      }
      const page = nbRes.data as unknown as PageEnvelope<NotebookRow>;
      const notebook = page.items.find((n) => n.slug === slug);
      if (notebook === undefined) {
        setState({ phase: "notfound" });
        return;
      }

      const health =
        healthRes.error === undefined && healthRes.data !== undefined
          ? (healthRes.data as unknown as HealthResult)
          : null;
      const healthError =
        health === null
          ? `GET /api/v1/notebooks/${slug}/health failed (${healthRes.response?.status ?? "network"}).`
          : null;

      const papersPage =
        papersRes.error === undefined && papersRes.data !== undefined
          ? (papersRes.data as unknown as PageEnvelope<PaperRow>)
          : null;
      const papersError =
        papersPage === null
          ? `GET /api/v1/notebooks/${slug}/papers failed (${papersRes.response?.status ?? "network"}).`
          : null;

      setState({
        phase: "loaded",
        notebook,
        health,
        healthError,
        papers: papersPage?.items ?? [],
        papersError,
      });
    })();
    return () => {
      cancelled = true;
    };
  }, [api, slug, reloadKey]);

  if (state.phase === "loading") {
    return (
      <p aria-live="polite" className="reg-telemetry" data-testid="detail-status">
        Loading notebook…
      </p>
    );
  }

  if (state.phase === "error") {
    return (
      <p aria-live="polite" className="reg-telemetry" data-testid="detail-status">
        {state.detail}
      </p>
    );
  }

  if (state.phase === "notfound") {
    return (
      <section aria-labelledby="nb-title">
        <div className="section-header">
          <h2 id="nb-title">Notebook not found</h2>
        </div>
        <p className="reg-telemetry" data-testid="detail-status">
          No notebook registered with slug <span className="chip">{slug}</span>.
        </p>
        <p>
          <Link to="/">Back to notebooks →</Link>
        </p>
      </section>
    );
  }

  const { notebook, health, healthError, papers, papersError } = state;
  return (
    <article className="with-margin" aria-labelledby="nb-title">
      <div>
        <header className="section-header">
          <h2 id="nb-title" className="detail-title" data-testid="detail-title">
            {notebook.display_name || notebook.slug}
          </h2>
          {notebook.description !== null && notebook.description !== "" && (
            <p className="reg-editorial note-muted">{notebook.description}</p>
          )}
          <div className="notebook-meta reg-telemetry">
            <span className="chip">{notebook.slug}</span>
            <span className="chip">{notebook.notebook_kind}</span>
            {notebook.discovery_category !== null &&
              notebook.discovery_category !== "" && (
                <span className="chip">{notebook.discovery_category}</span>
              )}
            <span className="chip">parse: {notebook.parse_status}</span>
          </div>
          <RenameControl
            slug={notebook.slug}
            displayName={notebook.display_name}
            onRenamed={(stored) => patchNotebook({ display_name: stored })}
          />
        </header>

        <HealthPanel
          slug={notebook.slug}
          health={health}
          healthError={healthError}
          onReconciled={reload}
        />

        <PapersTable
          slug={notebook.slug}
          papers={papers}
          papersError={papersError}
          onChanged={reload}
        />

        {/* Graph views (arx-b3): Tier-0 accessible neighbor explorer
            + opt-in Tier-2 3-D view; feature-detects the a45 API. */}
        <p className="reg-telemetry">
          <Link
            to={`/notebooks/${notebook.slug}/graph`}
            data-testid="graph-link"
          >
            Citation graph →
          </Link>
        </p>

        <AddSourcePanel
          slug={notebook.slug}
          notebookKind={notebook.notebook_kind}
          onAdded={reload}
        />

        <IngestPanel
          slug={notebook.slug}
          notebookKind={notebook.notebook_kind}
          onRunFinished={reload}
        />

        <TopicEditor
          slug={notebook.slug}
          category={notebook.discovery_category}
          description={notebook.description}
          onSaved={(category, description) =>
            patchNotebook({ discovery_category: category, description })
          }
        />

        <DiscoveryPanel slug={notebook.slug} onPapersChanged={reload} />

        <DangerZone slug={notebook.slug} />
      </div>

      <aside className="margin-note" aria-label="Provenance">
        <dl>
          <dt className="microlabel">created</dt>
          <dd>{notebook.created_at}</dd>
          <dt className="microlabel">corpus version</dt>
          <dd>{health?.corpus_version != null ? `v${health.corpus_version}` : "—"}</dd>
          <dt className="microlabel">embedder</dt>
          <dd>{health?.embedder_version ?? "—"}</dd>
          <dt className="microlabel">chunker</dt>
          <dd>{health?.chunker_version ?? "—"}</dd>
          <dt className="microlabel">marker written</dt>
          <dd>{health?.marker_created_at ?? "—"}</dd>
        </dl>
        <p>
          <a
            href={`/api/v1/notebooks/${notebook.slug}/export`}
            download={`${notebook.slug}.tar`}
            data-testid="export-link"
          >
            Download export (.tar) →
          </a>
        </p>
      </aside>
    </article>
  );
}
