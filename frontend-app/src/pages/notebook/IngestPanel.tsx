/**
 * Ingest panel [T] (brief §7.2): trigger + SSE-fed stage stepper with
 * the poll as authoritative fallback (useIngestProgress). States:
 *
 *  - live: stepper rows advance on stage events (arx-a23 servers);
 *    on the A1 spine a LABELED tri-state fallback line replaces the
 *    stepper ("stage events unavailable…") — the brief's mandated
 *    degraded mode, never a fake stepper.
 *  - failure: pinned at the failing stage (when stage events exist)
 *    with the redacted stderr tail in a monospace well; exit code
 *    shown either way.
 *  - queue honesty: concurrency is 1 by design; a 409 on trigger is
 *    surfaced verbatim ("an ingest is already in flight…").
 *
 * a11y: ONE mounted aria-live line announces per PHASE (trigger,
 * terminal outcome), never per poll tick or SSE frame (spec §5.3-A).
 */
import { useEffect, useRef, useState } from "react";
import { useApi } from "../../api/ApiProvider";
import { errorDetail } from "../../api/errors";
import {
  INGEST_STAGES,
  useIngestProgress,
  type EventSourceFactory,
  type StageState,
} from "./useIngestProgress";

/** Stage rows rendered per notebook kind: the parse stages (mineru /
 * latexml) only exist for textbook-kind pipelines. */
const ARXIV_STAGES = ["preflight", "chunk", "embed", "index"] as const;

const STATE_LABEL: Record<StageState, string> = {
  pending: "pending",
  started: "running",
  finished: "done",
  failed: "failed",
};

const STATE_BADGE: Record<StageState, string> = {
  pending: "badge",
  started: "badge badge-warn",
  finished: "badge badge-ok",
  failed: "badge badge-down",
};

function statusBadgeClass(status: string): string {
  switch (status) {
    case "succeeded":
      return "badge badge-ok";
    case "running":
      return "badge badge-warn";
    case "failed":
      return "badge badge-down";
    default:
      return "badge";
  }
}

export function IngestPanel({
  slug,
  notebookKind,
  onRunFinished,
  eventSourceFactory,
  pollIntervalMs,
}: {
  slug: string;
  notebookKind: string;
  /** Fires once per watched run reaching a terminal state (reload
   * health/papers — a successful ingest changes both). */
  onRunFinished?: () => void;
  eventSourceFactory?: EventSourceFactory;
  pollIntervalMs?: number;
}) {
  const api = useApi();
  const { latest, stages, transport, watching, watch } = useIngestProgress(
    slug,
    { eventSourceFactory, pollIntervalMs },
  );
  const [line, setLine] = useState("");
  const [busy, setBusy] = useState(false);

  const expectedStages =
    notebookKind === "textbook" ? INGEST_STAGES : ARXIV_STAGES;
  const haveStageEvents = Object.keys(stages).length > 0;

  // Announce terminal transitions once (per PHASE, not per tick).
  // Only runs this panel actually watched are news — a stale terminal
  // row found on first mount is history. hasWatchedRef flips when the
  // hook enters a watch (trigger-initiated or auto-watch of an
  // in-flight run found at mount).
  const announcedRef = useRef<string>("");
  const hasWatchedRef = useRef(false);
  if (watching) hasWatchedRef.current = true;
  useEffect(() => {
    if (latest === null || !latest.terminal) return;
    const key = `${latest.run_id ?? "?"}:${latest.status}`;
    if (announcedRef.current === key) return;
    announcedRef.current = key;
    if (!hasWatchedRef.current) return;
    setLine(
      latest.status === "succeeded"
        ? `Ingest run ${latest.run_id ?? "?"} succeeded.`
        : `Ingest run ${latest.run_id ?? "?"} ${latest.status}` +
            (latest.exit_code != null ? ` (exit ${latest.exit_code}).` : "."),
    );
    onRunFinished?.();
    // eslint-disable-next-line react-hooks/exhaustive-deps -- announce on latest only
  }, [latest]);

  async function trigger() {
    setBusy(true);
    setLine("Triggering ingest…");
    const { data, error, response } = await api.POST(
      "/api/v1/notebooks/{slug}/ingest",
      { params: { path: { slug } } },
    );
    setBusy(false);
    if (error !== undefined || data === undefined) {
      setLine(
        errorDetail(error) ??
          `POST /api/v1/notebooks/${slug}/ingest failed (${response?.status ?? "network"}).`,
      );
      return;
    }
    const run = data as unknown as { run_id?: number };
    setLine(`Ingest run ${run.run_id ?? "?"} started.`);
    watch();
  }

  const running = latest?.status === "running" || watching;
  const failedStage = (Object.entries(stages) as [string, StageState][]).find(
    ([, s]) => s === "failed",
  )?.[0];

  return (
    // data-transport lets tests await the SSE ready handshake before
    // triggering (deterministic stepper assertions); no visual role.
    <section aria-labelledby="ingest-h" data-transport={transport}>
      <div className="section-header">
        <h3 id="ingest-h">Ingest</h3>
      </div>

      <div className="health-line">
        <button
          type="button"
          onClick={() => void trigger()}
          disabled={busy || running}
          data-testid="ingest-trigger"
        >
          Run ingest
        </button>
        <span
          className={statusBadgeClass(latest?.status ?? "none")}
          data-testid="ingest-status-badge"
        >
          {latest?.status ?? "none"}
        </span>
        {running && (
          <span className="reg-telemetry note-muted" data-testid="ingest-transport">
            {transport === "sse"
              ? "live stage events (SSE)"
              : "polling /ingest/latest every 2 s"}
          </span>
        )}
      </div>

      <p aria-live="polite" className="reg-telemetry" data-testid="ingest-line">
        {line}
      </p>

      {haveStageEvents && (
        <div className="table-scroll">
          <table className="data" data-testid="ingest-stepper">
            <thead>
              <tr>
                <th scope="col">stage</th>
                <th scope="col">state</th>
              </tr>
            </thead>
            <tbody>
              {expectedStages.map((stage) => {
                const state: StageState = stages[stage] ?? "pending";
                return (
                  <tr key={stage} data-stage={stage} data-state={state}>
                    <td>
                      <span className="chip">{stage}</span>
                    </td>
                    <td>
                      <span className={STATE_BADGE[state]}>
                        {STATE_LABEL[state]}
                      </span>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {!haveStageEvents && running && transport === "poll" && (
        <p className="reg-telemetry note-muted" data-testid="stepper-fallback">
          Stage events unavailable from this server build — showing run
          status only (tri-state poll).
        </p>
      )}

      {latest !== null && latest.status !== "none" && (
        <dl className="run-meta reg-telemetry" data-testid="ingest-run-meta">
          <dt className="microlabel">run</dt>
          <dd>{latest.run_id ?? "—"}</dd>
          <dt className="microlabel">started</dt>
          <dd>{latest.started_at ?? "—"}</dd>
          <dt className="microlabel">finished</dt>
          <dd>{latest.finished_at ?? "—"}</dd>
          <dt className="microlabel">exit</dt>
          <dd>{latest.exit_code ?? "—"}</dd>
        </dl>
      )}

      {latest?.status === "failed" && (
        <div data-testid="ingest-failure">
          <p className="reg-telemetry malformed-note">
            {failedStage !== undefined
              ? `Run failed at the ${failedStage} stage.`
              : "Run failed."}
          </p>
          {latest.stderr_tail != null && latest.stderr_tail !== "" && (
            <pre className="well" data-testid="ingest-stderr">
              {latest.stderr_tail}
            </pre>
          )}
        </div>
      )}
    </section>
  );
}
