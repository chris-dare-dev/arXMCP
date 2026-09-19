/**
 * useObsFeed: the snapshot/stream merge race (frames buffered until
 * the snapshot resolves; duplicates dropped by seq; nothing lost),
 * retention capping, and the transient-error retry path.
 */
import { render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { ObsPage, ObsResult } from "../../api/obs";
import { FakeEventSource } from "./testDoubles";
import { useObsFeed, type RingEvent } from "./useObsFeed";

interface Item extends RingEvent {
  label: string;
}

function Probe({
  fetchPage,
  maxRetained,
}: {
  fetchPage: (q: { limit?: number; since_seq?: number }) => Promise<ObsResult<Item>>;
  maxRetained?: number;
}) {
  const feed = useObsFeed<Item>("logs", fetchPage, {
    eventSourceFactory: (u) => new FakeEventSource(u),
    pollIntervalMs: 20,
    maxRetained,
  });
  return (
    <div>
      <span data-testid="avail">{feed.availability}</span>
      <span data-testid="transport">{feed.transport}</span>
      <span data-testid="stream-lost">{String(feed.streamLost)}</span>
      <button type="button" data-testid="retry" onClick={feed.retry}>
        retry
      </button>
      <span data-testid="seqs">
        {feed.entries
          .map((e) => (e.kind === "event" ? e.event.seq : `gap${e.dropped}`))
          .join(",")}
      </span>
    </div>
  );
}

function pageOf(items: Item[], latest: number): ObsPage<Item> {
  return {
    format_version: 1,
    items: [...items].reverse(),
    total: items.length,
    limit: 500,
    offset: 0,
    latest_seq: latest,
  };
}

describe("useObsFeed", () => {
  it("buffers stream frames during the snapshot and merges without dupes or loss", async () => {
    FakeEventSource.reset();
    let releaseSnapshot: (() => void) | null = null;
    const gate = new Promise<void>((r) => (releaseSnapshot = r));
    const fetchPage = async (): Promise<ObsResult<Item>> => {
      await gate;
      return {
        kind: "ok",
        page: pageOf(
          [
            { seq: 1, ts: 1, label: "a" },
            { seq: 2, ts: 2, label: "b" },
          ],
          2,
        ),
      };
    };
    render(<Probe fetchPage={fetchPage} />);
    const es = FakeEventSource.instances[0];
    es.emit("ready", { topics: ["logs"], cursors: { logs: 2 } });
    // Frame 2 duplicates a snapshot row; frame 3 is genuinely new —
    // both arrive BEFORE the snapshot resolves.
    es.emit("logs", { seq: 2, ts: 2, label: "b" });
    es.emit("logs", { seq: 3, ts: 3, label: "c" });
    releaseSnapshot!();
    await waitFor(() =>
      expect(screen.getByTestId("seqs").textContent).toBe("1,2,3"),
    );
    expect(screen.getByTestId("avail").textContent).toBe("ok");
  });

  it("caps client retention at maxRetained (newest kept)", async () => {
    FakeEventSource.reset();
    const fetchPage = async (): Promise<ObsResult<Item>> => ({
      kind: "ok",
      page: pageOf(
        Array.from({ length: 6 }, (_, i) => ({
          seq: i + 1,
          ts: i + 1,
          label: String(i + 1),
        })),
        6,
      ),
    });
    render(<Probe fetchPage={fetchPage} maxRetained={4} />);
    await waitFor(() =>
      expect(screen.getByTestId("seqs").textContent).toBe("3,4,5,6"),
    );
  });

  it("keeps polling through transient errors after a good snapshot", async () => {
    FakeEventSource.reset();
    let calls = 0;
    const fetchPage = async (q: {
      since_seq?: number;
    }): Promise<ObsResult<Item>> => {
      calls += 1;
      if (calls === 1) {
        return { kind: "ok", page: pageOf([{ seq: 1, ts: 1, label: "a" }], 1) };
      }
      if (calls === 2) return { kind: "error", detail: "GET failed (503)" };
      return {
        kind: "ok",
        page:
          (q.since_seq ?? 0) >= 2
            ? pageOf([], 2)
            : pageOf([{ seq: 2, ts: 2, label: "late" }], 2),
      };
    };
    render(<Probe fetchPage={fetchPage} />);
    const es = FakeEventSource.instances[0];
    await waitFor(() =>
      expect(screen.getByTestId("avail").textContent).toBe("ok"),
    );
    es.fail(); // degrade to the poll
    await waitFor(() =>
      expect(screen.getByTestId("seqs").textContent).toBe("1,2"),
    );
  });

  it("retry resets streamLost so a recovered stream drops the reconnect banner", async () => {
    FakeEventSource.reset();
    let calls = 0;
    const fetchPage = async (): Promise<ObsResult<Item>> => {
      calls += 1;
      if (calls === 1) return { kind: "error", detail: "GET failed (503)" };
      return { kind: "ok", page: pageOf([{ seq: 1, ts: 1, label: "a" }], 1) };
    };
    render(<Probe fetchPage={fetchPage} />);
    await waitFor(() =>
      expect(screen.getByTestId("avail").textContent).toBe("error"),
    );
    // The first stream dies too — the reconnect signal latches.
    FakeEventSource.instances[0].fail();
    await waitFor(() =>
      expect(screen.getByTestId("stream-lost").textContent).toBe("true"),
    );
    // Retry: fresh snapshot succeeds AND a fresh stream comes up.
    screen.getByTestId("retry").click();
    await waitFor(() =>
      expect(screen.getByTestId("avail").textContent).toBe("ok"),
    );
    const es2 = FakeEventSource.instances[1];
    es2.emit("ready", { topics: ["logs"], cursors: { logs: 1 } });
    await waitFor(() =>
      expect(screen.getByTestId("transport").textContent).toBe("sse"),
    );
    // Without the reset, this stays "true" and the surfaces render the
    // "switched to polling" banner beside a "live (SSE)" status line.
    expect(screen.getByTestId("stream-lost").textContent).toBe("false");
  });
});
