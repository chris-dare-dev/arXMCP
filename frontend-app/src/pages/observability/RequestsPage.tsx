/**
 * Requests surface [T] (brief §7.4 D.2; AC-B.19): the session-lane
 * hero (R1 — one lane per agent role, tool calls as pulses, fill =
 * cache tier, danger ring = error, cap meters per lane, ghost-lane
 * teaching empty state), the request table (R2 — latency µ-bar vs the
 * window p95, tier chip, bytes, status), the per-request waterfall
 * drawer (R3 — semantic phases from phases_ms; the waterfall renders
 * ONLY phases that actually ran, single-bar fallback otherwise;
 * retrieval is dense-only shipped, so no phantom rerank phase is ever
 * drawn), and a cap-rejection strip (R6-lite via the status facet).
 *
 * The table is the accessible surface (Tier-0 discipline); the lane
 * canvas is an enhancement with a text summary. Nothing on this page
 * animates continuously (NO-10/11 have no 3D here; pulses are static
 * marks re-rendered on data change).
 *
 * The time window is anchored to the DATA (newest event ts), not the
 * wall clock — live it tracks now, paused/fixture it is deterministic.
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import type { RequestEvent, SessionRow } from "../../api/obs";
import { useObsApi } from "../../api/ObsProvider";
import { CapMeter, FilterChip, facetCounts, fmtClock } from "./shared";
import {
  useObsFeed,
  type EventSourceFactory,
  type RingEvent,
} from "./useObsFeed";

type ReqEvent = RequestEvent & RingEvent;

/** The four fixed pipeline roles (brief §7.0 — fixed colors/lanes,
 * used identically everywhere). Observed extra roles get lanes after
 * these; null-role traffic lands in the "(no role)" lane. */
export const PIPELINE_ROLES = [
  "sketcher",
  "autoformalizer",
  "tactician",
  "fixer",
] as const;

const NO_ROLE = "(no role)";
const WINDOW_SECONDS = 300;
const MAX_TABLE_ROWS = 200;

/** Categorical, non-status fills for cache tiers (CO-4: status colors
 * stay on status-bearing elements; tier is provenance, not status). */
const TIER_FILLS = [
  "var(--accent)",
  "var(--ink)",
  "var(--ink-muted)",
  "var(--rule-color-strong)",
];

function percentile(sorted: number[], p: number): number | null {
  if (sorted.length === 0) return null;
  const idx = Math.min(
    sorted.length - 1,
    Math.max(0, Math.ceil(p * sorted.length) - 1),
  );
  return sorted[idx];
}

function statusBadgeClass(status: string): string {
  if (status === "ok") return "badge badge-ok";
  if (status === "error") return "badge badge-down";
  if (status === "denied") return "badge badge-ops";
  if (status === "cap") return "badge badge-warn";
  return "badge";
}

// ---------------------------------------------------------------------------
// R1 — session-lane canvas (the hero)
// ---------------------------------------------------------------------------

function LaneCanvas({
  events,
  sessions,
}: {
  events: ReqEvent[];
  sessions: SessionRow[] | null;
}) {
  const maxTs = events.length > 0 ? events[events.length - 1].ts : null;
  const t1 = maxTs ?? 0;
  const t0 = t1 - WINDOW_SECONDS;
  const windowEvents = maxTs === null ? [] : events.filter((e) => e.ts >= t0);

  const observedRoles = new Set(
    windowEvents.map((e) => e.role ?? NO_ROLE),
  );
  const lanes: string[] = [
    ...PIPELINE_ROLES,
    ...[...observedRoles]
      .filter((r) => !(PIPELINE_ROLES as readonly string[]).includes(r))
      .sort(),
  ];

  const tiers = [
    ...new Set(
      windowEvents
        .map((e) => e.cache_layer)
        .filter((t): t is string => t !== null && t !== undefined),
    ),
  ].sort();
  const tierFill = new Map(tiers.map((t, i) => [t, TIER_FILLS[i % TIER_FILLS.length]]));

  const ghost = windowEvents.length === 0;

  const sessionForRole = (role: string): SessionRow | null => {
    if (sessions === null || role === NO_ROLE) return null;
    return sessions.find((s) => s.roles_seen.includes(role)) ?? null;
  };

  return (
    <div
      className={ghost ? "lane-canvas lane-canvas-ghost" : "lane-canvas"}
      data-testid="lane-canvas"
    >
      <div className="lane-axis reg-telemetry">
        {maxTs !== null ? (
          <>
            <span>{fmtClock(t0)}</span>
            <span className="microlabel">
              {WINDOW_SECONDS / 60} min window (UTC)
            </span>
            <span>{fmtClock(t1)}</span>
          </>
        ) : (
          <span className="microlabel">no traffic window yet (UTC)</span>
        )}
      </div>
      {lanes.map((role) => {
        const laneEvents = windowEvents.filter(
          (e) => (e.role ?? NO_ROLE) === role,
        );
        const session = sessionForRole(role);
        return (
          <div className="lane" key={role} data-testid={`lane-${role}`}>
            <div className="lane-head">
              <span className="chip">{role}</span>
              {session !== null && (
                <span className="lane-caps">
                  {Object.entries(session.caps)
                    .slice(0, 3)
                    .map(([tool, cap]) => (
                      <CapMeter
                        key={tool}
                        label={tool}
                        used={cap.used}
                        limit={cap.limit}
                      />
                    ))}
                </span>
              )}
            </div>
            <svg
              className="lane-strip"
              viewBox="0 0 1000 28"
              preserveAspectRatio="none"
              role="img"
              aria-label={`${role} lane: ${laneEvents.length} call${
                laneEvents.length === 1 ? "" : "s"
              } in the window`}
            >
              <line
                x1="0"
                y1="14"
                x2="1000"
                y2="14"
                className="lane-baseline"
              />
              {laneEvents.map((e) => {
                // Inset the plot area so edge pulses (the newest event
                // anchors the window's right edge) never clip.
                const x = 10 + ((e.ts - t0) / WINDOW_SECONDS) * 980;
                const failed = e.status !== "ok";
                const fill =
                  e.cache_layer !== null && e.cache_layer !== undefined
                    ? tierFill.get(e.cache_layer)
                    : "var(--paper)";
                return (
                  <circle
                    key={e.seq}
                    cx={x}
                    cy="14"
                    r="6"
                    style={{ fill }}
                    className={failed ? "pulse pulse-error" : "pulse"}
                  >
                    <title>
                      {`${e.tool} · ${e.status} · ${e.latency_ms} ms · tier ${
                        e.cache_layer ?? "none"
                      }`}
                    </title>
                  </circle>
                );
              })}
            </svg>
          </div>
        );
      })}
      {ghost && (
        <p className="empty-state" data-testid="lane-ghost">
          No agent traffic in the window. Connect an agent with the{" "}
          <code className="reg-telemetry">Arxmcp-Agent-Role</code> header
          (sketcher, autoformalizer, tactician, fixer) — its tool calls appear
          as pulses in that role&apos;s lane.
        </p>
      )}
      {tiers.length > 0 && (
        <div className="lane-legend reg-telemetry" data-testid="lane-legend">
          <span className="microlabel">pulse fill = cache tier</span>
          {tiers.map((t) => (
            <span key={t} className="legend-item">
              <span
                className="legend-swatch"
                style={{ background: tierFill.get(t) }}
              />
              {t}
            </span>
          ))}
          <span className="legend-item">
            <span className="legend-swatch legend-swatch-error" />
            error ring
          </span>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// R3 — waterfall drawer
// ---------------------------------------------------------------------------

function WaterfallDrawer({
  event,
  sameTool,
  onClose,
}: {
  event: ReqEvent;
  sameTool: ReqEvent[];
  onClose: () => void;
}) {
  useEffect(() => {
    const onKey = (ev: KeyboardEvent) => {
      if (ev.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);

  const phases = Object.entries(event.phases_ms ?? {}).filter(
    ([, ms]) => typeof ms === "number",
  );
  const phasesTotal = phases.reduce((acc, [, ms]) => acc + ms, 0);
  const barTotal = Math.max(event.latency_ms, phasesTotal, 0.001);

  const latencies = sameTool.map((e) => e.latency_ms).sort((a, b) => a - b);
  const p50 = percentile(latencies, 0.5);
  const p95 = percentile(latencies, 0.95);

  return (
    <aside
      className="obs-drawer"
      aria-label={`Request detail: ${event.tool}`}
      data-testid="waterfall-drawer"
    >
      <div className="inspector-head">
        <span className="reg-telemetry">
          {event.tool} · seq {event.seq} · {fmtClock(event.ts)}
        </span>
        <button type="button" data-testid="drawer-close" onClick={onClose}>
          Close
        </button>
      </div>

      <div className="waterfall" data-testid="waterfall">
        <div className="waterfall-track">
          {phases.length > 0 ? (
            phases.map(([name, ms], i) => (
              <span
                key={name}
                className="waterfall-seg"
                data-testid={`phase-${name}`}
                style={{
                  width: `${(ms / barTotal) * 100}%`,
                  background: TIER_FILLS[i % TIER_FILLS.length],
                }}
                title={`${name}: ${ms} ms`}
              />
            ))
          ) : (
            <span
              className="waterfall-seg"
              data-testid="phase-total"
              style={{ width: "100%", background: "var(--accent)" }}
              title={`total: ${event.latency_ms} ms`}
            />
          )}
          {p50 !== null && p50 <= barTotal && (
            <span
              className="ruler-tick"
              style={{ left: `${(p50 / barTotal) * 100}%` }}
              title={`window p50 ${p50} ms`}
            />
          )}
          {p95 !== null && p95 <= barTotal && (
            <span
              className="ruler-tick ruler-tick-p95"
              style={{ left: `${(p95 / barTotal) * 100}%` }}
              title={`window p95 ${p95} ms`}
            />
          )}
        </div>
        <ul className="waterfall-list reg-telemetry">
          {phases.length > 0 ? (
            phases.map(([name, ms]) => (
              <li key={name}>
                {name}: {ms} ms
              </li>
            ))
          ) : (
            <li data-testid="waterfall-fallback">
              total {event.latency_ms} ms — no phase capture on this call
            </li>
          )}
        </ul>
        <p className="microlabel" data-testid="waterfall-ruler">
          {p50 !== null && p95 !== null
            ? `window p50 ${p50} ms · p95 ${p95} ms over ${latencies.length} ${event.tool} call${latencies.length === 1 ? "" : "s"} retained`
            : "no comparable calls retained for a p50/p95 ruler"}
        </p>
      </div>

      <dl className="run-meta reg-telemetry" data-testid="drawer-meta">
        <dt className="microlabel">status</dt>
        <dd>
          <span className={statusBadgeClass(event.status)}>{event.status}</span>
        </dd>
        {event.error_code !== null && event.error_code !== undefined && (
          <>
            <dt className="microlabel">error_code</dt>
            <dd>{event.error_code}</dd>
          </>
        )}
        <dt className="microlabel">latency</dt>
        <dd>{event.latency_ms} ms</dd>
        {event.cache_layer !== null && event.cache_layer !== undefined && (
          <>
            <dt className="microlabel">cache tier</dt>
            <dd>{event.cache_layer}</dd>
          </>
        )}
        {event.result_bytes !== null && event.result_bytes !== undefined && (
          <>
            <dt className="microlabel">bytes</dt>
            <dd>{event.result_bytes}</dd>
          </>
        )}
        {event.k !== null && event.k !== undefined && (
          <>
            <dt className="microlabel">k</dt>
            <dd>{event.k}</dd>
          </>
        )}
        {event.corpus_version !== null && event.corpus_version !== undefined && (
          <>
            <dt className="microlabel">corpus</dt>
            <dd>v{event.corpus_version}</dd>
          </>
        )}
        {event.session_id !== null && event.session_id !== undefined && (
          <>
            <dt className="microlabel">session</dt>
            <dd>
              <span className="chip">{event.session_id}</span>
            </dd>
          </>
        )}
        {event.notebook !== null && event.notebook !== undefined && (
          <>
            <dt className="microlabel">notebook</dt>
            <dd>
              <span className="chip">{event.notebook}</span>
            </dd>
          </>
        )}
        <dt className="microlabel">profile</dt>
        <dd>{event.profile ?? "default"}</dd>
      </dl>
    </aside>
  );
}

// ---------------------------------------------------------------------------
// The page
// ---------------------------------------------------------------------------

const TABLE_FACETS = [
  { field: "tool", read: (e: ReqEvent) => e.tool },
  { field: "status", read: (e: ReqEvent) => e.status },
  { field: "role", read: (e: ReqEvent) => e.role },
  { field: "session", read: (e: ReqEvent) => e.session_id },
] as const;

type TableFacetField = (typeof TABLE_FACETS)[number]["field"];

export function RequestsPage({
  eventSourceFactory,
  pollIntervalMs,
  sessionsPollMs = 5000,
}: {
  eventSourceFactory?: EventSourceFactory;
  pollIntervalMs?: number;
  sessionsPollMs?: number;
} = {}) {
  const obs = useObsApi();
  const fetchPage = useCallback(
    (q: { limit?: number; since_seq?: number }) => obs.requests(q),
    [obs],
  );
  const feed = useObsFeed<ReqEvent>("requests", fetchPage, {
    eventSourceFactory,
    pollIntervalMs,
  });

  // Sessions snapshot for the per-lane cap meters (authoritative
  // snapshot endpoint; quiet null when unavailable).
  const [sessions, setSessions] = useState<SessionRow[] | null>(null);
  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | null = null;
    const tick = async () => {
      const result = await obs.sessions();
      if (cancelled) return;
      if (result.kind === "ok") setSessions(result.page.items);
      if (result.kind !== "unavailable") {
        timer = setTimeout(() => void tick(), sessionsPollMs);
      }
    };
    void tick();
    return () => {
      cancelled = true;
      if (timer !== null) clearTimeout(timer);
    };
  }, [obs, sessionsPollMs]);

  const events = useMemo(
    () =>
      feed.entries
        .filter((e): e is { kind: "event"; event: ReqEvent } => e.kind === "event")
        .map((e) => e.event),
    [feed.entries],
  );

  // --- URL-addressable filters (cross-navigation from Logs lands here) ---
  const [searchParams, setSearchParams] = useSearchParams();
  const activeFacets = useMemo(() => {
    const active = new Map<TableFacetField, string>();
    for (const { field } of TABLE_FACETS) {
      const v = searchParams.get(field);
      if (v !== null && v !== "") active.set(field, v);
    }
    return active;
  }, [searchParams]);

  const toggleFacet = useCallback(
    (field: TableFacetField, value: string) => {
      const next = new URLSearchParams(searchParams);
      if (next.get(field) === value) next.delete(field);
      else next.set(field, value);
      setSearchParams(next, { replace: true });
    },
    [searchParams, setSearchParams],
  );

  const matches = useCallback(
    (event: ReqEvent, ignoreField?: TableFacetField) => {
      for (const { field, read } of TABLE_FACETS) {
        if (field === ignoreField) continue;
        const want = activeFacets.get(field);
        if (want !== undefined && (read(event) ?? "") !== want) return false;
      }
      return true;
    },
    [activeFacets],
  );

  const filtered = useMemo(() => events.filter((e) => matches(e)), [events, matches]);
  const tableRows = useMemo(
    () => [...filtered].reverse().slice(0, MAX_TABLE_ROWS),
    [filtered],
  );

  const windowP95 = useMemo(() => {
    const lat = filtered.map((e) => e.latency_ms).sort((a, b) => a - b);
    return percentile(lat, 0.95);
  }, [filtered]);

  const rejections = useMemo(
    () => events.filter((e) => e.status === "denied" || e.status === "cap").length,
    [events],
  );

  // --- Drawer selection ---
  const [selectedSeq, setSelectedSeq] = useState<number | null>(null);
  const selected = useMemo(
    () => events.find((e) => e.seq === selectedSeq) ?? null,
    [events, selectedSeq],
  );

  const statusText =
    feed.availability === "loading"
      ? "Loading request events…"
      : feed.availability === "unavailable"
        ? "Request events unavailable on this server build."
        : feed.availability === "error"
          ? (feed.errorDetail ?? "Request feed failed.")
          : `${filtered.length} of ${events.length} request event${
              events.length === 1 ? "" : "s"
            } retained · ${feed.transport === "sse" ? "live (SSE)" : "polling every 2 s"}`;

  return (
    <section aria-labelledby="requests-h" className="obs-page">
      <div className="section-header">
        <h2 id="requests-h">Requests</h2>
      </div>

      <p aria-live="polite" className="reg-telemetry" data-testid="requests-status">
        {statusText}
      </p>

      {feed.streamLost && feed.availability === "ok" && (
        <p className="obs-banner reg-telemetry" data-testid="requests-stream-banner">
          Live stream lost — switched to 2 s polling.
        </p>
      )}

      {feed.availability === "unavailable" && (
        <div className="empty-state" data-testid="requests-unavailable">
          <p>
            This server build does not expose{" "}
            <code className="reg-telemetry">GET /api/v1/requests</code>.
          </p>
          <p>
            The observability read-APIs ship with the arx-a23 server slice —
            run a build that includes it, then reload this page.
          </p>
        </div>
      )}

      {feed.availability === "error" && (
        <div className="empty-state" data-testid="requests-error">
          <p>{feed.errorDetail}</p>
          <button type="button" onClick={feed.retry}>
            Retry
          </button>
        </div>
      )}

      {feed.availability === "ok" && (
        <>
          <LaneCanvas events={events} sessions={sessions} />

          {rejections > 0 && (
            <p
              className="obs-banner reg-telemetry"
              data-testid="cap-rejection-strip"
            >
              {rejections} cap/authz rejection{rejections === 1 ? "" : "s"}{" "}
              retained — filter with the status chips below.
            </p>
          )}

          <div className="facet-row" data-testid="requests-facets">
            {TABLE_FACETS.map(({ field, read }) => {
              const counts = facetCounts(
                events.filter((e) => matches(e, field)),
                read,
              );
              const universe = facetCounts(events, read);
              const values = [...universe.keys()]
                .sort(
                  (a, b) =>
                    (universe.get(b) ?? 0) - (universe.get(a) ?? 0) ||
                    a.localeCompare(b),
                )
                .slice(0, 8);
              if (values.length === 0 && !activeFacets.has(field)) return null;
              return (
                <div key={field} className="facet-group" data-testid={`rfacet-${field}`}>
                  <span className="microlabel">{field}</span>
                  <div className="facet-chips">
                    {values.map((value) => (
                      <FilterChip
                        key={value}
                        value={value}
                        count={counts.get(value) ?? 0}
                        active={activeFacets.get(field) === value}
                        onToggle={() => toggleFacet(field, value)}
                      />
                    ))}
                  </div>
                </div>
              );
            })}
          </div>

          {tableRows.length === 0 ? (
            <div className="empty-state" data-testid="requests-empty">
              <p>No request events match.</p>
              <p>
                {activeFacets.size > 0
                  ? "Clear a facet chip to widen the view."
                  : "Events appear when agents call MCP tools through this server."}
              </p>
            </div>
          ) : (
            <div className="table-scroll">
              <table className="data" data-testid="requests-table">
                <thead>
                  <tr>
                    <th scope="col">time (UTC)</th>
                    <th scope="col">tool</th>
                    <th scope="col">status</th>
                    <th scope="col">latency</th>
                    <th scope="col">tier</th>
                    <th scope="col">bytes</th>
                    <th scope="col">session</th>
                    <th scope="col">role</th>
                  </tr>
                </thead>
                <tbody>
                  {tableRows.map((e) => (
                    <tr key={e.seq} data-testid="request-row">
                      <td>{fmtClock(e.ts)}</td>
                      <td>
                        <button
                          type="button"
                          className="row-detail-btn"
                          data-testid={`request-open-${e.seq}`}
                          aria-expanded={selectedSeq === e.seq}
                          onClick={() =>
                            setSelectedSeq((s) => (s === e.seq ? null : e.seq))
                          }
                        >
                          {e.tool}
                        </button>
                      </td>
                      <td>
                        <span className={statusBadgeClass(e.status)}>
                          {e.status}
                        </span>
                      </td>
                      <td>
                        <span className="latency-cell">
                          <span className="latency-bar-track">
                            <span
                              className="latency-bar"
                              style={{
                                width: `${
                                  windowP95 !== null && windowP95 > 0
                                    ? Math.min(
                                        (e.latency_ms / windowP95) * 100,
                                        100,
                                      )
                                    : 0
                                }%`,
                              }}
                            />
                          </span>
                          {e.latency_ms} ms
                        </span>
                      </td>
                      <td>{e.cache_layer ?? "-"}</td>
                      <td>{e.result_bytes ?? "-"}</td>
                      <td>{e.session_id ?? "-"}</td>
                      <td>{e.role ?? "-"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {windowP95 !== null && (
            <p className="obs-retention microlabel" data-testid="requests-p95">
              latency bars scaled to the retained-window p95 ({windowP95} ms) ·
              in-memory ring · nothing persists across restarts
            </p>
          )}

          {selected !== null && (
            <WaterfallDrawer
              event={selected}
              sameTool={events.filter((e) => e.tool === selected.tool)}
              onClose={() => setSelectedSeq(null)}
            />
          )}
        </>
      )}
    </section>
  );
}
