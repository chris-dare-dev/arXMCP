/**
 * Corpus-version.json stats + drift indicator + reconcile action
 * (AC-B.18; brief §7.1 "Drift indicator"). Quiet single line when the
 * marker is clean; amber sentence + reconcile affordance when drifted
 * — the papers.txt-vs-marker off-by-one class 211 recorded as the
 * historical cross-repo failure mode. Status colors appear here
 * because this IS a status-bearing element (CO-4).
 *
 * The stat block renders the marker's own numbers (paper_count,
 * chunk_count, version, created_at) with the live recount shown as a
 * sub-value only where it disagrees.
 */
import { useRef, useState } from "react";
import { useApi } from "../../api/ApiProvider";
import type { HealthResult, ReconcileResult } from "../../api/types";
import { refreshFlash } from "../../motion/anime";

type ReconcileState =
  | { phase: "idle" }
  | { phase: "running" }
  | { phase: "done"; result: ReconcileResult }
  | { phase: "error"; detail: string };

const BADGE: Record<string, { cls: string; label: string }> = {
  ok: { cls: "badge badge-ok", label: "ok" },
  drift: { cls: "badge badge-warn", label: "drift" },
  no_marker: { cls: "badge badge-ops", label: "no marker" },
  malformed_marker: { cls: "badge badge-down", label: "malformed" },
};

function sentenceFor(health: HealthResult): string {
  if (health.status === "ok") {
    return (
      `marker and LanceDB agree — ${health.marker_chunk_count} chunks / `
      + `${health.marker_paper_count} papers at corpus v${health.corpus_version}.`
    );
  }
  // drift / no_marker / malformed_marker: the server's detail sentence
  // is the authoritative operator copy; fall back to an owned line.
  return health.detail ?? `marker status: ${health.status}`;
}

export function HealthPanel({
  slug,
  health,
  healthError,
  onReconciled,
}: {
  slug: string;
  health: HealthResult | null;
  healthError: string | null;
  onReconciled: () => void;
}) {
  const api = useApi();
  const [rec, setRec] = useState<ReconcileState>({ phase: "idle" });
  const statRef = useRef<HTMLDListElement>(null);

  async function runReconcile() {
    setRec({ phase: "running" });
    const { data, error, response } = await api.POST(
      "/api/v1/notebooks/{slug}/reconcile-marker",
      { params: { path: { slug } } },
    );
    if (error !== undefined || data === undefined) {
      setRec({
        phase: "error",
        detail: `POST /api/v1/notebooks/${slug}/reconcile-marker failed (${response?.status ?? "network"}).`,
      });
      return;
    }
    setRec({ phase: "done", result: data as unknown as ReconcileResult });
    onReconciled();
    if (statRef.current !== null) {
      // Refresh flash on the stat block — the shipped 400 ms grammar;
      // gated on prefers-reduced-motion inside the wrapper.
      void refreshFlash(statRef.current);
    }
  }

  const badge = health !== null ? BADGE[health.status] : null;
  const hasMarker =
    health !== null && (health.status === "ok" || health.status === "drift");

  return (
    <section aria-labelledby="health-h">
      <div className="section-header">
        <h3 id="health-h">Corpus health</h3>
      </div>

      <p aria-live="polite" className="reg-telemetry health-line" data-testid="health-status">
        {healthError !== null && <span className="malformed-note">{healthError}</span>}
        {healthError === null && health === null && "Reading corpus-version.json marker…"}
        {health !== null && (
          <>
            <span className={badge?.cls}>{badge?.label}</span>
            <span
              className={
                health.status === "drift"
                  ? "drift-note"
                  : health.status === "malformed_marker"
                    ? "malformed-note"
                    : undefined
              }
              data-testid="health-sentence"
            >
              {sentenceFor(health)}
            </span>
          </>
        )}
      </p>

      {hasMarker && health !== null && (
        <dl className="stat-grid" data-testid="stat-block" ref={statRef}>
          <div>
            <dt className="microlabel">corpus version</dt>
            <dd className="stat-value">v{health.corpus_version}</dd>
          </div>
          <div>
            <dt className="microlabel">chunks (marker)</dt>
            <dd className="stat-value">
              {health.marker_chunk_count}
              {health.drift !== 0 && (
                <span className="stat-sub drift-note">
                  actual {health.actual_chunk_count}
                </span>
              )}
            </dd>
          </div>
          <div>
            <dt className="microlabel">papers (marker)</dt>
            <dd className="stat-value">
              {health.marker_paper_count}
              {health.marker_paper_count !== health.actual_paper_count && (
                <span className="stat-sub drift-note">
                  actual {health.actual_paper_count}
                </span>
              )}
            </dd>
          </div>
          <div>
            <dt className="microlabel">marker written</dt>
            <dd className="stat-value-sm">{health.marker_created_at ?? "—"}</dd>
          </div>
        </dl>
      )}

      {health?.status === "drift" && (
        <p>
          <button
            type="button"
            onClick={() => void runReconcile()}
            disabled={rec.phase === "running"}
          >
            Reconcile marker from recount
          </button>
        </p>
      )}

      <p aria-live="polite" className="reg-telemetry" data-testid="reconcile-status">
        {rec.phase === "running" && "Reconciling marker from a live recount…"}
        {rec.phase === "done" &&
          `Marker reconciled: ${rec.result.before.chunk_count} → ${rec.result.after.chunk_count} chunks (drift resolved ${rec.result.drift_resolved}).`}
        {rec.phase === "error" && rec.detail}
      </p>
    </section>
  );
}
