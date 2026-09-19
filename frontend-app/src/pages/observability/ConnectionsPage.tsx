/**
 * Connections surface [T] (brief §7.4 D.3; AC-B.19): C1 server trust
 * header (one sentence-of-state), C2 session roster with activity
 * dots, per-cap depleting meters and the hourly window, cross-links
 * into Logs/Requests filtered by session prefix, a copyable connect
 * snippet in the empty state, and the ingest stage-event history
 * (shares the R4 ring the b2 stepper consumes live).
 *
 * Transport: the roster polls GET /api/v1/sessions (the authoritative
 * snapshot — the SSE `sessions` topic is only a change notification,
 * so a quiet poll IS the documented consumption pattern); the ingest
 * history rides the shared ring-feed hook (SSE with poll fallback).
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import type { IngestEventRow, ObsStatus, SessionRow } from "../../api/obs";
import { useObsApi } from "../../api/ObsProvider";
import { CapMeter, FilterChip, facetCounts, fmtClock } from "./shared";
import {
  useObsFeed,
  type EventSourceFactory,
  type RingEvent,
} from "./useObsFeed";

type IngestEvent = IngestEventRow & RingEvent;

const ACTIVE_WINDOW_SECONDS = 60;
const MAX_HISTORY_ROWS = 100;
const CONNECT_HEADER = "Arxmcp-Agent-Role: sketcher";

type RosterState =
  | { phase: "loading" }
  | { phase: "ok"; rows: SessionRow[] }
  | { phase: "unavailable" }
  | { phase: "error"; detail: string };

export function ConnectionsPage({
  eventSourceFactory,
  pollIntervalMs,
  sessionsPollMs = 5000,
  /** Injectable clock (tests pin the activity-dot cutoff). */
  now = () => Date.now() / 1000,
}: {
  eventSourceFactory?: EventSourceFactory;
  pollIntervalMs?: number;
  sessionsPollMs?: number;
  now?: () => number;
} = {}) {
  const obs = useObsApi();

  // --- C1 trust header + C2 roster (one poll drives both) ---
  const [roster, setRoster] = useState<RosterState>({ phase: "loading" });
  const [status, setStatus] = useState<ObsStatus | null>(null);
  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | null = null;
    const tick = async () => {
      const [sessionsResult, statusBody] = await Promise.all([
        obs.sessions(),
        obs.status(),
      ]);
      if (cancelled) return;
      setStatus(statusBody);
      if (sessionsResult.kind === "ok") {
        setRoster({ phase: "ok", rows: sessionsResult.page.items });
      } else if (sessionsResult.kind === "unavailable") {
        setRoster({ phase: "unavailable" });
        return; // structural — stop polling
      } else {
        setRoster((r) =>
          r.phase === "ok" ? r : { phase: "error", detail: sessionsResult.detail },
        );
      }
      timer = setTimeout(() => void tick(), sessionsPollMs);
    };
    void tick();
    return () => {
      cancelled = true;
      if (timer !== null) clearTimeout(timer);
    };
  }, [obs, sessionsPollMs]);

  const [copied, setCopied] = useState(false);
  const copySnippet = useCallback(() => {
    void navigator.clipboard?.writeText(CONNECT_HEADER).then(
      () => setCopied(true),
      () => setCopied(false),
    );
  }, []);

  // --- Ingest history (R4 ring) ---
  const fetchIngest = useCallback(
    (q: { limit?: number; since_seq?: number }) => obs.ingestEvents(q),
    [obs],
  );
  const ingestFeed = useObsFeed<IngestEvent>("ingest", fetchIngest, {
    eventSourceFactory,
    pollIntervalMs,
  });

  const ingestEvents = useMemo(
    () =>
      ingestFeed.entries
        .filter(
          (e): e is { kind: "event"; event: IngestEvent } => e.kind === "event",
        )
        .map((e) => e.event),
    [ingestFeed.entries],
  );

  const [searchParams, setSearchParams] = useSearchParams();
  const activeSlug = searchParams.get("slug");
  const toggleSlug = useCallback(
    (slug: string) => {
      const next = new URLSearchParams(searchParams);
      if (next.get("slug") === slug) next.delete("slug");
      else next.set("slug", slug);
      setSearchParams(next, { replace: true });
    },
    [searchParams, setSearchParams],
  );

  const filteredIngest = useMemo(
    () =>
      activeSlug === null
        ? ingestEvents
        : ingestEvents.filter((e) => e.slug === activeSlug),
    [activeSlug, ingestEvents],
  );
  const historyRows = useMemo(
    () => [...filteredIngest].reverse().slice(0, MAX_HISTORY_ROWS),
    [filteredIngest],
  );
  const slugCounts = useMemo(
    () => facetCounts(ingestEvents, (e) => e.slug),
    [ingestEvents],
  );

  const sessionCount = roster.phase === "ok" ? roster.rows.length : null;

  // The badge carries the status word; the sentence carries the rest.
  const trustSentence =
    status === null
      ? "server state unknown — GET /status did not answer"
      : `${
          status.corpus_version !== null
            ? `corpus v${status.corpus_version}`
            : "no corpus version"
        }${sessionCount !== null ? ` · ${sessionCount} session${sessionCount === 1 ? "" : "s"} tracked` : ""}`;

  return (
    <section aria-labelledby="connections-h" className="obs-page">
      <div className="section-header">
        <h2 id="connections-h">Connections</h2>
      </div>

      {/* C1 — the trust header: one sentence of state. */}
      <p
        aria-live="polite"
        className="reg-telemetry trust-header"
        data-testid="trust-header"
      >
        {status !== null && (
          <span
            className={
              status.status === "ready" || status.status === "ok"
                ? "badge badge-ok"
                : "badge badge-warn"
            }
          >
            {status.status}
          </span>
        )}{" "}
        {trustSentence}
      </p>

      {/* C2 — session roster. */}
      <h3 className="section-header">Sessions</h3>
      {roster.phase === "loading" && (
        <p className="reg-telemetry" data-testid="roster-loading">
          Loading sessions…
        </p>
      )}
      {roster.phase === "unavailable" && (
        <div className="empty-state" data-testid="roster-unavailable">
          <p>
            This server build does not expose{" "}
            <code className="reg-telemetry">GET /api/v1/sessions</code>.
          </p>
          <p>
            The observability read-APIs ship with the arx-a23 server slice —
            run a build that includes it, then reload this page.
          </p>
        </div>
      )}
      {roster.phase === "error" && (
        <p className="reg-telemetry" data-testid="roster-error">
          {roster.detail}
        </p>
      )}
      {roster.phase === "ok" && roster.rows.length === 0 && (
        <div className="empty-state" data-testid="roster-empty">
          <p>No sessions tracked. Agents get a session on their first MCP call.</p>
          <p>
            Send the role header so calls land in a named lane:{" "}
            <code className="reg-telemetry" data-testid="connect-snippet">
              {CONNECT_HEADER}
            </code>{" "}
            <button type="button" data-testid="copy-snippet" onClick={copySnippet}>
              {copied ? "Copied" : "Copy header"}
            </button>
          </p>
        </div>
      )}
      {roster.phase === "ok" && roster.rows.length > 0 && (
        <ul className="session-roster" data-testid="session-roster">
          {roster.rows.map((s) => {
            const active = now() - s.last_seen_at < ACTIVE_WINDOW_SECONDS;
            return (
              <li
                key={s.session_id_prefix}
                className={active ? "session-row" : "session-row session-row-idle"}
                data-testid={`session-${s.session_id_prefix}`}
              >
                <div className="session-head reg-telemetry">
                  <span
                    className={active ? "activity-dot activity-dot-active" : "activity-dot"}
                    role="img"
                    aria-label={active ? "active in the last minute" : "idle"}
                  />
                  <span className="chip">{s.session_id_prefix}</span>
                  {s.roles_seen.map((r) => (
                    <span key={r} className="chip">
                      {r}
                    </span>
                  ))}
                  <span className="note-muted">
                    created {fmtClock(s.created_at)} · last seen{" "}
                    {fmtClock(s.last_seen_at)} UTC
                  </span>
                  <span className="session-links">
                    <Link
                      to={`/logs?session=${encodeURIComponent(s.session_id_prefix)}`}
                    >
                      logs
                    </Link>{" "}
                    <Link
                      to={`/requests?session=${encodeURIComponent(s.session_id_prefix)}`}
                    >
                      requests
                    </Link>
                  </span>
                </div>
                <div className="session-caps">
                  {Object.entries(s.caps).map(([tool, cap]) => (
                    <CapMeter
                      key={tool}
                      label={tool}
                      used={cap.used}
                      limit={cap.limit}
                    />
                  ))}
                  <CapMeter
                    label={`hourly (${Math.round(s.hourly.window_seconds / 60)} min window)`}
                    used={s.hourly.used}
                    limit={s.hourly.limit}
                  />
                </div>
              </li>
            );
          })}
        </ul>
      )}

      {/* Ingest history — the R4 stage-event ring. */}
      <h3 className="section-header">Ingest history</h3>
      <p
        aria-live="polite"
        className="reg-telemetry"
        data-testid="ingest-history-status"
      >
        {ingestFeed.availability === "loading" && "Loading ingest events…"}
        {ingestFeed.availability === "unavailable" &&
          "Ingest stage events unavailable on this server build (arx-a23 read-APIs)."}
        {ingestFeed.availability === "error" &&
          (ingestFeed.errorDetail ?? "Ingest event feed failed.")}
        {ingestFeed.availability === "ok" &&
          `${filteredIngest.length} stage event${filteredIngest.length === 1 ? "" : "s"} retained · ${
            ingestFeed.transport === "sse" ? "live (SSE)" : "polling every 2 s"
          }`}
      </p>

      {ingestFeed.availability === "ok" && (
        <>
          {slugCounts.size > 0 && (
            <div className="facet-group" data-testid="ingest-slug-facet">
              <span className="microlabel">notebook</span>
              <div className="facet-chips">
                {[...slugCounts.keys()].sort().map((slug) => (
                  <FilterChip
                    key={slug}
                    value={slug}
                    count={slugCounts.get(slug) ?? 0}
                    active={activeSlug === slug}
                    onToggle={() => toggleSlug(slug)}
                  />
                ))}
              </div>
            </div>
          )}
          {historyRows.length === 0 ? (
            <div className="empty-state" data-testid="ingest-history-empty">
              <p>No ingest stage events retained.</p>
              <p>
                Trigger a notebook ingest — stage events (preflight, chunk,
                embed, index) land here as the run progresses.
              </p>
            </div>
          ) : (
            <div className="table-scroll">
              <table className="data" data-testid="ingest-history-table">
                <thead>
                  <tr>
                    <th scope="col">time (UTC)</th>
                    <th scope="col">kind</th>
                    <th scope="col">notebook</th>
                    <th scope="col">stage</th>
                    <th scope="col">phase</th>
                    <th scope="col">run</th>
                    <th scope="col">detail</th>
                  </tr>
                </thead>
                <tbody>
                  {historyRows.map((e) => (
                    <tr key={e.seq} data-testid="ingest-history-row">
                      <td>{fmtClock(e.ts)}</td>
                      <td>{e.kind}</td>
                      <td>
                        <span className="chip">{e.slug}</span>
                      </td>
                      <td>{e.stage}</td>
                      <td
                        className={
                          e.phase === "failed" ? "malformed-note" : undefined
                        }
                      >
                        {e.phase}
                      </td>
                      <td>{e.run_id ?? "-"}</td>
                      <td className="detail-cell">
                        {e.detail !== undefined ? JSON.stringify(e.detail) : "-"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}
    </section>
  );
}
