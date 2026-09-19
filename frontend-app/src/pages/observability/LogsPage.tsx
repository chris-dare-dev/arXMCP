/**
 * Logs surface [T] (brief §7.4 D.1; AC-B.19): live tail with
 * pause/scrollback + "N new lines" pill (the WCAG 2.2.2 pause
 * mechanism), closed-set facet rail (level / logger / event / tool /
 * session / role — NO query language), consecutive-duplicate collapse
 * (×N), a line inspector with sorted-key JSON + redaction notice, and
 * a retention banner honest about the ring buffer.
 *
 * Redaction-preserving rendering: every record entered the server's
 * ring AFTER RedactionFilter ran (AC-A.12) — this surface renders
 * fields verbatim and never re-derives anything from raw sources; the
 * inspector states the discipline explicitly.
 *
 * Motion rules: NO per-line animation (NO-12); auto-follow scrolls
 * instantly, never smooth; the only animated thing on this page is
 * the pill's 150 ms fade-in (clamped under reduced motion).
 */
import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { Link, useSearchParams } from "react-router-dom";
import type { LogRecord } from "../../api/obs";
import { useObsApi } from "../../api/ObsProvider";
import { facetCounts, FilterChip, fmtClock, fmtIso } from "./shared";
import {
  useObsFeed,
  type EventSourceFactory,
  type FeedEntry,
  type RingEvent,
} from "./useObsFeed";

type LogEvent = LogRecord & RingEvent;

/** The closed facet field set (finding 09 D.1 L2). */
const FACET_FIELDS = [
  { field: "level", read: (r: LogEvent) => (r.level ? String(r.level) : null) },
  { field: "logger", read: (r: LogEvent) => (r.name ? String(r.name) : null) },
  { field: "event", read: (r: LogEvent) => (r.event ? String(r.event) : null) },
  { field: "tool", read: (r: LogEvent) => (r.tool ? String(r.tool) : null) },
  {
    field: "session",
    read: (r: LogEvent) => (r.session_id ? String(r.session_id) : null),
  },
  { field: "role", read: (r: LogEvent) => (r.role ? String(r.role) : null) },
] as const;

type FacetField = (typeof FACET_FIELDS)[number]["field"];

const MAX_CHIPS_PER_FIELD = 12;

/** Attributes the inspector renders as chips + everything else as
 * sorted-key JSON. Excluded: the tail row already shows these. */
function inspectorJson(record: LogEvent): string {
  const sorted: Record<string, unknown> = {};
  for (const key of Object.keys(record).sort()) sorted[key] = record[key];
  return JSON.stringify(sorted, null, 2);
}

function levelClass(level: string | undefined): string {
  const lv = (level ?? "").toUpperCase();
  if (lv === "ERROR" || lv === "CRITICAL") return "log-level-down";
  if (lv === "WARNING" || lv === "WARN") return "log-level-warn";
  if (lv === "DEBUG") return "log-level-muted";
  return "log-level-info";
}

interface CollapsedRow {
  first: LogEvent;
  count: number;
}

/** L5 pattern-collapse: consecutive records with identical
 * (level, logger, message) fold into one row with a ×N badge. */
function collapseRows(events: LogEvent[]): CollapsedRow[] {
  const rows: CollapsedRow[] = [];
  for (const event of events) {
    const prev = rows[rows.length - 1];
    if (
      prev !== undefined &&
      prev.first.level === event.level &&
      prev.first.name === event.name &&
      prev.first.message === event.message
    ) {
      prev.count += 1;
    } else {
      rows.push({ first: event, count: 1 });
    }
  }
  return rows;
}

export function LogsPage({
  eventSourceFactory,
  pollIntervalMs,
}: {
  eventSourceFactory?: EventSourceFactory;
  pollIntervalMs?: number;
} = {}) {
  const obs = useObsApi();
  const fetchPage = useCallback(
    (q: { limit?: number; since_seq?: number }) => obs.logsTail(q),
    [obs],
  );
  const feed = useObsFeed<LogEvent>("logs", fetchPage, {
    eventSourceFactory,
    pollIntervalMs,
  });

  // --- Facets (URL-addressable per brief §7: ?level=ERROR&tool=…) ---
  const [searchParams, setSearchParams] = useSearchParams();
  const activeFacets = useMemo(() => {
    const active = new Map<FacetField, string>();
    for (const { field } of FACET_FIELDS) {
      const v = searchParams.get(field);
      if (v !== null && v !== "") active.set(field, v);
    }
    return active;
  }, [searchParams]);

  const toggleFacet = useCallback(
    (field: FacetField, value: string) => {
      const next = new URLSearchParams(searchParams);
      if (next.get(field) === value) next.delete(field);
      else next.set(field, value);
      setSearchParams(next, { replace: true });
    },
    [searchParams, setSearchParams],
  );

  // --- Pause / follow (WCAG 2.2.2) ---
  const [follow, setFollow] = useState(true);
  const [frozen, setFrozen] = useState<FeedEntry<LogEvent>[] | null>(null);
  const viewportRef = useRef<HTMLDivElement | null>(null);

  const liveEntries = feed.entries;
  const displayedEntries = frozen ?? liveEntries;

  const frozenLastSeq = useMemo(() => {
    if (frozen === null) return 0;
    for (let i = frozen.length - 1; i >= 0; i -= 1) {
      const e = frozen[i];
      if (e.kind === "event") return e.event.seq;
    }
    return 0;
  }, [frozen]);

  const newWhilePaused = useMemo(() => {
    if (frozen === null) return 0;
    let n = 0;
    for (const e of liveEntries) {
      if (e.kind === "event" && e.event.seq > frozenLastSeq) n += 1;
    }
    return n;
  }, [frozen, frozenLastSeq, liveEntries]);

  const pause = useCallback(() => {
    setFollow(false);
    setFrozen((f) => f ?? liveEntries);
  }, [liveEntries]);

  const resume = useCallback(() => {
    setFrozen(null);
    setFollow(true);
    const vp = viewportRef.current;
    if (vp !== null) vp.scrollTop = vp.scrollHeight; // instant, never smooth
  }, []);

  // Auto-follow: instant scroll on new entries (NO-12: no smooth).
  useLayoutEffect(() => {
    if (!follow) return;
    const vp = viewportRef.current;
    if (vp !== null) vp.scrollTop = vp.scrollHeight;
  }, [follow, displayedEntries]);

  // Scrolling up pauses follow; returning to the bottom resumes.
  const onScroll = useCallback(() => {
    const vp = viewportRef.current;
    if (vp === null) return;
    const fromBottom = vp.scrollHeight - vp.scrollTop - vp.clientHeight;
    if (fromBottom > 40) {
      if (follow) pause();
    } else if (!follow) {
      resume();
    }
  }, [follow, pause, resume]);

  // --- Filtering + collapse over the displayed window ---
  const displayedEvents = useMemo(
    () =>
      displayedEntries.filter(
        (e): e is Extract<FeedEntry<LogEvent>, { kind: "event" }> =>
          e.kind === "event",
      ),
    [displayedEntries],
  );

  const matches = useCallback(
    (record: LogEvent, ignoreField?: FacetField) => {
      for (const { field, read } of FACET_FIELDS) {
        if (field === ignoreField) continue;
        const want = activeFacets.get(field);
        if (want !== undefined && read(record) !== want) return false;
      }
      return true;
    },
    [activeFacets],
  );

  const filteredEvents = useMemo(
    () => displayedEvents.map((e) => e.event).filter((r) => matches(r)),
    [displayedEvents, matches],
  );

  const collapsed = useMemo(() => collapseRows(filteredEvents), [filteredEvents]);

  // --- Inspector (L4) ---
  const [selectedSeq, setSelectedSeq] = useState<number | null>(null);
  const selected = useMemo(
    () =>
      selectedSeq === null
        ? null
        : (displayedEvents.find((e) => e.event.seq === selectedSeq)?.event ?? null),
    [displayedEvents, selectedSeq],
  );
  useEffect(() => {
    if (selectedSeq !== null && selected === null) setSelectedSeq(null);
  }, [selected, selectedSeq]);

  const statusText =
    feed.availability === "loading"
      ? "Loading log tail…"
      : feed.availability === "unavailable"
        ? "Log tail unavailable on this server build."
        : feed.availability === "error"
          ? (feed.errorDetail ?? "Log tail request failed.")
          : `${collapsed.length} line${collapsed.length === 1 ? "" : "s"} shown · ${
              frozen !== null ? "paused" : "following"
            } · ${feed.transport === "sse" ? "live (SSE)" : "polling every 2 s"}`;

  return (
    <section aria-labelledby="logs-h" className="obs-page">
      <div className="section-header">
        <h2 id="logs-h">Logs</h2>
      </div>

      <p aria-live="polite" className="reg-telemetry" data-testid="logs-status">
        {statusText}
      </p>

      {feed.streamLost && feed.availability === "ok" && (
        <p className="obs-banner reg-telemetry" data-testid="logs-stream-banner">
          Live stream lost — switched to 2 s polling. The seq cursor keeps the
          tail gap-free within ring capacity.
        </p>
      )}

      {feed.availability === "unavailable" && (
        <div className="empty-state" data-testid="logs-unavailable">
          <p>
            This server build does not expose{" "}
            <code className="reg-telemetry">GET /api/v1/logs/tail</code>.
          </p>
          <p>
            The observability read-APIs ship with the arx-a23 server slice —
            run a build that includes it, then reload this page.
          </p>
        </div>
      )}

      {feed.availability === "error" && (
        <div className="empty-state" data-testid="logs-error">
          <p>{feed.errorDetail}</p>
          <button type="button" onClick={feed.retry}>
            Retry
          </button>
        </div>
      )}

      {feed.availability === "ok" && (
        <div className="obs-split">
          {/* L2 facet rail: queryless chips over the closed field set. */}
          <aside className="facet-rail" aria-label="Log facets">
            {FACET_FIELDS.map(({ field, read }) => {
              const counts = facetCounts(
                displayedEvents
                  .map((e) => e.event)
                  .filter((r) => matches(r, field)),
                read,
              );
              const universe = facetCounts(
                displayedEvents.map((e) => e.event),
                read,
              );
              const values = [...universe.keys()]
                .sort(
                  (a, b) =>
                    (universe.get(b) ?? 0) - (universe.get(a) ?? 0) ||
                    a.localeCompare(b),
                )
                .slice(0, MAX_CHIPS_PER_FIELD);
              if (values.length === 0 && !activeFacets.has(field)) return null;
              return (
                <div key={field} className="facet-group" data-testid={`facet-${field}`}>
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
          </aside>

          <div className="obs-main">
            {/* Tail controls: the explicit WCAG 2.2.2 pause mechanism. */}
            <div className="tail-controls">
              {frozen === null ? (
                <button type="button" data-testid="logs-pause" onClick={pause}>
                  Pause
                </button>
              ) : (
                <button type="button" data-testid="logs-resume" onClick={resume}>
                  Resume{newWhilePaused > 0 ? ` (${newWhilePaused} new)` : ""}
                </button>
              )}
            </div>

            {/* L1 tail viewport. */}
            <div className="tail-wrap">
              <div
                className="log-viewport reg-telemetry"
                data-testid="logs-viewport"
                ref={viewportRef}
                onScroll={onScroll}
              >
                {collapsed.length === 0 && (
                  <div className="empty-state" data-testid="logs-empty">
                    <p>No log records match.</p>
                    <p>
                      {activeFacets.size > 0
                        ? "Clear a facet chip to widen the view."
                        : "Records appear when the server handles traffic — make any MCP tool call or trigger an ingest."}
                    </p>
                  </div>
                )}
                {frozen === null &&
                  displayedEntries
                    .filter(
                      (e): e is Extract<FeedEntry<LogEvent>, { kind: "gap" }> =>
                        e.kind === "gap",
                    )
                    .slice(-1)
                    .map((gap) => (
                      <p
                        key={gap.key}
                        className="log-gap"
                        data-testid="logs-gap"
                      >
                        — stream gap: {gap.dropped} record
                        {gap.dropped === 1 ? "" : "s"} dropped while this client
                        lagged; the ring endpoint still has them —
                      </p>
                    ))}
                {collapsed.map((row) => (
                  <button
                    type="button"
                    key={row.first.seq}
                    className={`log-row ${levelClass(row.first.level)}`}
                    data-testid="log-row"
                    data-seq={row.first.seq}
                    aria-expanded={selectedSeq === row.first.seq}
                    onClick={() =>
                      setSelectedSeq((s) =>
                        s === row.first.seq ? null : row.first.seq,
                      )
                    }
                  >
                    <span className="log-ts">{fmtClock(row.first.ts)}</span>
                    <span className="log-level">
                      {String(row.first.level ?? "").toUpperCase() || "-"}
                    </span>
                    <span className="log-logger">{row.first.name ?? "-"}</span>
                    <span className="log-msg">{row.first.message ?? ""}</span>
                    {row.count > 1 && (
                      <span className="log-collapse" data-testid="log-collapse">
                        {"×"}
                        {row.count}
                      </span>
                    )}
                  </button>
                ))}
              </div>
              {frozen !== null && newWhilePaused > 0 && (
                <button
                  type="button"
                  className="new-lines-pill"
                  data-testid="logs-pill"
                  onClick={resume}
                >
                  {newWhilePaused} new line{newWhilePaused === 1 ? "" : "s"}{" "}
                  {"↓"}
                </button>
              )}
            </div>

            {/* L6 retention banner: honest about the ring. */}
            <p className="obs-retention microlabel" data-testid="logs-retention">
              in-memory ring · {feed.ringTotal} records at snapshot · newest
              retained here · nothing persists across restarts
            </p>

            {/* L4 line inspector. */}
            {selected !== null && (
              <aside
                className="line-inspector"
                aria-label="Log line detail"
                data-testid="log-inspector"
              >
                <div className="inspector-head">
                  <span className="reg-telemetry">
                    seq {selected.seq} · {fmtIso(selected.ts)}
                  </span>
                  <button type="button" onClick={() => setSelectedSeq(null)}>
                    Close
                  </button>
                </div>
                <div className="inspector-chips">
                  {selected.session_id !== undefined &&
                    selected.session_id !== null && (
                      <Link
                        className="chip"
                        to={`/requests?session=${encodeURIComponent(String(selected.session_id))}`}
                      >
                        session {String(selected.session_id)}
                      </Link>
                    )}
                  {selected.tool !== undefined && selected.tool !== null && (
                    <Link
                      className="chip"
                      to={`/requests?tool=${encodeURIComponent(String(selected.tool))}`}
                    >
                      tool {String(selected.tool)}
                    </Link>
                  )}
                </div>
                <pre className="well inspector-json">{inspectorJson(selected)}</pre>
                <p className="microlabel" data-testid="inspector-redaction">
                  redacted at source: sensitive fields were stripped by the
                  server before this record entered the ring (INFO and above)
                </p>
              </aside>
            )}
          </div>
        </div>
      )}
    </section>
  );
}
