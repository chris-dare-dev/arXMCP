/**
 * useObsFeed — one live ring feed (logs / requests / ingest topics)
 * over the IF-2 transport discipline the b2 ingest stepper
 * established: ONE EventSource per mounted page, opened at mount; a
 * stream error closes it for good and the hook degrades to since_seq
 * polling (the a23 endpoints' documented degraded mode — every SSE
 * topic has a GET twin). A 404 on the snapshot GET is the A1 spine:
 * the surface renders an honest "not on this server build" state and
 * neither stream nor poll ever spams.
 *
 * Ordering/dedupe: ring events carry a monotone `seq`. The stream is
 * opened BEFORE the snapshot resolves and frames are buffered, then
 * merged by seq — no event between "snapshot taken" and "stream live"
 * can be lost, and duplicates (frame also present in the snapshot)
 * are dropped by the seq cursor.
 *
 * Explicit `gap` frames (server-side drop-oldest on a lagging
 * consumer) become inline gap entries — the finding-09 L1 error-state
 * design: name the gap, never fake continuity.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import type { ObsPage, ObsResult } from "../../api/obs";
import type {
  EventSourceFactory,
  EventSourceLike,
} from "../notebook/useIngestProgress";

export type { EventSourceFactory, EventSourceLike };

export interface RingEvent {
  seq: number;
  ts: number;
}

export type FeedEntry<T extends RingEvent> =
  | { kind: "event"; event: T }
  | { kind: "gap"; dropped: number; key: number };

export type FeedAvailability = "loading" | "ok" | "unavailable" | "error";

export type FeedTransport = "idle" | "sse" | "poll";

export interface ObsFeed<T extends RingEvent> {
  /** Chronological (oldest → newest). */
  entries: FeedEntry<T>[];
  availability: FeedAvailability;
  /** Set when availability === "error". */
  errorDetail: string | null;
  transport: FeedTransport;
  /** True once the SSE stream errored (reconnect-banner signal). */
  streamLost: boolean;
  /** Ring total at snapshot time (retention honesty). */
  ringTotal: number;
  latestSeq: number;
  /** Re-run the snapshot fetch (error-state retry). */
  retry: () => void;
}

export interface ObsFeedOptions {
  pollIntervalMs?: number;
  /** Snapshot page size (ring endpoints cap at 500). */
  snapshotLimit?: number;
  /** Client-side retention cap (brief §7.4 wants virtualization only
   * beyond ~5k retained lines — we bound retention below that; the
   * ring stays the source of truth and the retention banner says so). */
  maxRetained?: number;
  eventSourceFactory?: EventSourceFactory;
}

const defaultEventSourceFactory: EventSourceFactory = (url) =>
  typeof EventSource === "undefined" ? null : new EventSource(url);

let gapKeyCounter = 0;

export function useObsFeed<T extends RingEvent>(
  topic: "logs" | "requests" | "ingest",
  fetchPage: (q: { limit?: number; since_seq?: number }) => Promise<ObsResult<T>>,
  {
    pollIntervalMs = 2000,
    snapshotLimit = 500,
    maxRetained = 2000,
    eventSourceFactory,
  }: ObsFeedOptions = {},
): ObsFeed<T> {
  const [entries, setEntries] = useState<FeedEntry<T>[]>([]);
  const [availability, setAvailability] = useState<FeedAvailability>("loading");
  const [errorDetail, setErrorDetail] = useState<string | null>(null);
  const [transport, setTransport] = useState<FeedTransport>("idle");
  const [streamLost, setStreamLost] = useState(false);
  const [ringTotal, setRingTotal] = useState(0);
  const [latestSeq, setLatestSeq] = useState(0);
  const [retryKey, setRetryKey] = useState(0);

  // Mutable machinery (no re-renders): the seq cursor, the
  // pre-snapshot frame buffer, poll-loop invalidation, and sync
  // mirrors of async state the poll loop must read mid-tick.
  const lastSeqRef = useRef(0);
  const snapshotReadyRef = useRef(false);
  const bufferRef = useRef<FeedEntry<T>[]>([]);
  const tokenRef = useRef(0);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const availabilityRef = useRef<FeedAvailability>("loading");
  const transportRef = useRef<FeedTransport>("idle");
  transportRef.current = transport;
  const makeEventSource = eventSourceFactory ?? defaultEventSourceFactory;

  const appendEntries = useCallback(
    (fresh: FeedEntry<T>[]) => {
      const accepted: FeedEntry<T>[] = [];
      for (const entry of fresh) {
        if (entry.kind === "gap") {
          accepted.push(entry);
          continue;
        }
        if (entry.event.seq > lastSeqRef.current) {
          lastSeqRef.current = entry.event.seq;
          accepted.push(entry);
        }
      }
      if (accepted.length === 0) return;
      setLatestSeq(lastSeqRef.current);
      setEntries((prev) => {
        const next = [...prev, ...accepted];
        return next.length > maxRetained
          ? next.slice(next.length - maxRetained)
          : next;
      });
    },
    [maxRetained],
  );

  /** Ring pages arrive newest-first; the feed is chronological. */
  const absorbPage = useCallback(
    (page: ObsPage<T>) => {
      const chronological = [...page.items].reverse();
      appendEntries(
        chronological.map((event) => ({ kind: "event" as const, event })),
      );
    },
    [appendEntries],
  );

  // --- SSE subscription: one per mount, opened immediately ---
  useEffect(() => {
    // A fresh attempt (mount or retry) clears the reconnect signal:
    // without this, a retry that successfully re-establishes SSE would
    // keep streamLost=true and the surfaces would show the "switched
    // to polling" banner beside a "live (SSE)" status line.
    setStreamLost(false);
    const es = makeEventSource(`/api/v1/events/stream?topics=${topic}`);
    if (es === null) {
      setTransport("poll");
      return;
    }
    const deliver = (entry: FeedEntry<T>) => {
      if (snapshotReadyRef.current) appendEntries([entry]);
      else bufferRef.current.push(entry);
    };
    es.addEventListener("ready", () => setTransport("sse"));
    es.addEventListener(topic, (ev) => {
      let event: T;
      try {
        event = JSON.parse(String(ev.data)) as T;
      } catch {
        return;
      }
      deliver({ kind: "event", event });
    });
    es.addEventListener("gap", (ev) => {
      let payload: { dropped?: number };
      try {
        payload = JSON.parse(String(ev.data)) as { dropped?: number };
      } catch {
        return;
      }
      gapKeyCounter += 1;
      deliver({ kind: "gap", dropped: payload.dropped ?? 0, key: gapKeyCounter });
    });
    es.onerror = () => {
      // 404 on the A1 spine / dropped stream: close for this mount,
      // poll from the cursor (no EventSource auto-retry spam).
      es.close();
      setStreamLost(true);
      setTransport("poll");
    };
    return () => es.close();
    // eslint-disable-next-line react-hooks/exhaustive-deps -- one subscription per mount/topic
  }, [topic, retryKey]);

  // --- Snapshot, then the degraded-mode poll loop ---
  useEffect(() => {
    tokenRef.current += 1;
    const token = tokenRef.current;
    snapshotReadyRef.current = false;
    bufferRef.current = [];
    lastSeqRef.current = 0;
    setEntries([]);
    setAvailability("loading");
    availabilityRef.current = "loading";

    const schedule = (fn: () => void) => {
      timerRef.current = setTimeout(fn, pollIntervalMs);
    };

    const loop = async () => {
      if (tokenRef.current !== token) return;
      if (availabilityRef.current !== "ok") return;
      if (transportRef.current === "sse") {
        // Stream is live: no network work, just stay armed in case it
        // drops later.
        schedule(() => void loop());
        return;
      }
      const result = await fetchPage({
        limit: snapshotLimit,
        since_seq: lastSeqRef.current,
      });
      if (tokenRef.current !== token) return;
      if (result.kind === "unavailable") {
        // A structural 404 after a working snapshot = server swapped
        // out under us. Stop; the page states the endpoint is gone.
        setAvailability("unavailable");
        availabilityRef.current = "unavailable";
        return;
      }
      if (result.kind === "ok") absorbPage(result.page);
      // Transient errors: keep polling quietly.
      schedule(() => void loop());
    };

    void (async () => {
      const result = await fetchPage({ limit: snapshotLimit });
      if (tokenRef.current !== token) return;
      if (result.kind === "unavailable") {
        setAvailability("unavailable");
        availabilityRef.current = "unavailable";
        return;
      }
      if (result.kind === "error") {
        setAvailability("error");
        availabilityRef.current = "error";
        setErrorDetail(result.detail);
        return;
      }
      setRingTotal(result.page.total);
      absorbPage(result.page);
      setAvailability("ok");
      availabilityRef.current = "ok";
      setErrorDetail(null);
      // Merge frames that raced the snapshot, then go live.
      snapshotReadyRef.current = true;
      appendEntries(bufferRef.current);
      bufferRef.current = [];
      schedule(() => void loop());
    })();

    return () => {
      tokenRef.current += 1;
      if (timerRef.current !== null) {
        clearTimeout(timerRef.current);
        timerRef.current = null;
      }
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- mount/retry only
  }, [retryKey]);

  const retry = useCallback(() => setRetryKey((k) => k + 1), []);

  return {
    entries,
    availability,
    errorDetail,
    transport,
    streamLost,
    ringTotal,
    latestSeq,
    retry,
  };
}
