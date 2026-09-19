/**
 * Ingest-run watcher: SSE-fed stage events with a polling fallback
 * (brief §7.2 "Live progress transport: SSE with 2s-poll fallback").
 *
 * Two server generations are in play:
 *  - the A1 API spine (this branch) has ONLY the tri-state poll
 *    (GET /api/v1/notebooks/{slug}/ingest/latest);
 *  - the arx-a23 branch adds the IF-2 multiplexed SSE endpoint
 *    (GET /api/v1/events/stream?topics=ingest) emitting stage events
 *    {kind, slug, stage, phase, run_id?, paper_id?, detail?, seq}
 *    with stages preflight→mineru→latexml→chunk→embed→index plus the
 *    "run"/"queue" pseudo-stages (server/observability/events.py
 *    publish_ingest_stage_event).
 *
 * Strategy:
 *  - ONE EventSource subscription for the mounted lifetime of the
 *    hook, opened at mount — NOT per run. The a23 tracker emits
 *    `preflight` inside the trigger request itself, so a subscription
 *    opened after the 202 returns would always miss it. If the stream
 *    errors (404 on the A1 spine, drop), it closes for good and
 *    transport reads "poll" — the hook degrades, never breaks.
 *  - Stage maps are keyed by run_id: the first event of a new run
 *    resets the map (no cross-run bleed, no wipe of same-run events
 *    that raced the trigger response).
 *  - While a run is live the poll ALWAYS runs at 2 s — it is the
 *    authoritative terminal state on every server generation and
 *    carries stderr_tail.
 *
 * Both the EventSource constructor and the poll cadence are
 * injectable — jsdom has no EventSource, and tests drive scripted
 * frames + fast polls deterministically.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { useApi } from "../../api/ApiProvider";
import type { IngestStageEvent, LatestIngest } from "../../api/types";

/** Canonical stage vocabulary (arx-a23 INGEST_STAGES). */
export const INGEST_STAGES = [
  "preflight",
  "mineru",
  "latexml",
  "chunk",
  "embed",
  "index",
] as const;

export type StageState = "pending" | "started" | "finished" | "failed";

/** Minimal EventSource surface the hook needs (test seam). */
export interface EventSourceLike {
  addEventListener(type: string, listener: (ev: MessageEvent) => void): void;
  close(): void;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any -- matches lib.dom's EventSource.onerror this-type
  onerror: ((this: any, ev: Event) => unknown) | null;
}

export type EventSourceFactory = (url: string) => EventSourceLike | null;

const defaultEventSourceFactory: EventSourceFactory = (url) =>
  typeof EventSource === "undefined" ? null : new EventSource(url);

export type Transport = "idle" | "sse" | "poll";

export interface IngestProgress {
  /** Latest run row from the poll (authoritative tri-state). */
  latest: LatestIngest | null;
  /** Per-stage states for the most recent run seen over SSE; empty on
   * the A1 spine. */
  stages: Partial<Record<string, StageState>>;
  transport: Transport;
  /** True between watch() and the terminal poll. */
  watching: boolean;
  /** Begin watching (call after a successful trigger POST). */
  watch: () => void;
  /** One-shot poll (initial mount / manual refresh). */
  refresh: () => Promise<LatestIngest | null>;
}

export interface IngestProgressOptions {
  pollIntervalMs?: number;
  eventSourceFactory?: EventSourceFactory;
}

export function useIngestProgress(
  slug: string,
  { pollIntervalMs = 2000, eventSourceFactory }: IngestProgressOptions = {},
): IngestProgress {
  const api = useApi();
  const [latest, setLatest] = useState<LatestIngest | null>(null);
  const [stages, setStages] = useState<Partial<Record<string, StageState>>>({});
  const [transport, setTransport] = useState<Transport>("idle");
  const [watching, setWatching] = useState(false);

  // Mutable machinery; the token invalidates superseded poll loops.
  const tokenRef = useRef(0);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const stageRunRef = useRef<number | string | null>(null);
  const makeEventSource = eventSourceFactory ?? defaultEventSourceFactory;

  const stopPoll = useCallback(() => {
    tokenRef.current += 1;
    if (timerRef.current !== null) {
      clearTimeout(timerRef.current);
      timerRef.current = null;
    }
    setWatching(false);
  }, []);

  const pollOnce = useCallback(async (): Promise<LatestIngest | null> => {
    const { data, error } = await api.GET(
      "/api/v1/notebooks/{slug}/ingest/latest",
      { params: { path: { slug } } },
    );
    if (error !== undefined || data === undefined) return null;
    const raw = data as unknown as LatestIngest;
    // Wire normalization (live-E2E find): the m9 store persists
    // INGEST_STATUS_SUCCESS = "success" and api_v1 passes the column
    // through verbatim, while the SPA's canonical success token is
    // "succeeded". Normalize at the single poll seam so every consumer
    // (badge class, announce line, tests) sees one vocabulary
    // regardless of server generation.
    const row: LatestIngest =
      raw.status === "success" ? { ...raw, status: "succeeded" } : raw;
    setLatest(row);
    return row;
  }, [api, slug]);

  const watch = useCallback(() => {
    stopPoll();
    const token = tokenRef.current;
    setWatching(true);
    const tick = async () => {
      if (tokenRef.current !== token) return;
      const row = await pollOnce();
      if (tokenRef.current !== token) return;
      if (row !== null && row.terminal) {
        stopPoll();
        return;
      }
      timerRef.current = setTimeout(() => void tick(), pollIntervalMs);
    };
    void tick();
  }, [pollIntervalMs, pollOnce, stopPoll]);

  // --- SSE subscription: one per mounted slug, opened immediately ---
  useEffect(() => {
    const es = makeEventSource("/api/v1/events/stream?topics=ingest");
    if (es === null) {
      setTransport("poll");
      return;
    }
    es.addEventListener("ready", () => setTransport("sse"));
    es.addEventListener("ingest", (ev) => {
      let event: IngestStageEvent;
      try {
        event = JSON.parse(String(ev.data)) as IngestStageEvent;
      } catch {
        return;
      }
      if (event.slug !== slug) return;
      if (event.stage === "run" || event.stage === "queue") {
        if (event.phase === "finished" || event.phase === "failed") {
          // Terminal run event: surface the final row promptly rather
          // than waiting out the poll interval.
          void pollOnce();
        }
        return;
      }
      const runKey = event.run_id ?? "unknown";
      setStages((m) => {
        let base = m;
        if (stageRunRef.current !== runKey) {
          // First event of a new run: fresh map (no cross-run bleed).
          stageRunRef.current = runKey;
          base = {};
        }
        const prior = base[event.stage];
        // Never regress finished/failed back to started (events can
        // interleave across papers within one run).
        if (
          event.phase === "started" &&
          (prior === "finished" || prior === "failed")
        ) {
          return base === m ? m : { ...base };
        }
        const next: StageState =
          event.phase === "failed"
            ? "failed"
            : event.phase === "finished"
              ? "finished"
              : "started";
        return { ...base, [event.stage]: next };
      });
    });
    es.onerror = () => {
      // 404 on the A1 spine / dropped stream: close for this mount and
      // rely on the poll (no EventSource auto-retry spam).
      es.close();
      setTransport("poll");
    };
    return () => es.close();
    // eslint-disable-next-line react-hooks/exhaustive-deps -- one subscription per slug
  }, [slug]);

  // Initial mount: one-shot poll; auto-watch a run already in flight.
  useEffect(() => {
    let cancelled = false;
    void pollOnce().then((row) => {
      if (!cancelled && row !== null && row.status === "running") watch();
    });
    return () => {
      cancelled = true;
      stopPoll();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- mount/slug only
  }, [slug]);

  return { latest, stages, transport, watching, watch, refresh: pollOnce };
}
