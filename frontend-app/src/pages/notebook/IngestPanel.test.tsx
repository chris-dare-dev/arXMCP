/**
 * Ingest panel: trigger → watch loop against a scripted server double;
 * SSE stage events (fake EventSource) advancing the stepper; the
 * pinned-failure state; the 409 queue-honesty path; and the labeled
 * tri-state fallback when the stream is absent (A1 spine).
 */
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ApiProvider } from "../../api/ApiProvider";
import { makeClient } from "../../api/client";
import { jsonResponse } from "../../api/mock";
import type { LatestIngest } from "../../api/types";
import { IngestPanel } from "./IngestPanel";
import type { EventSourceLike } from "./useIngestProgress";

/** Scriptable ingest server double: tests mutate `latest` and flip
 * `conflict` to script the poll's world. */
function ingestServer() {
  const state: { latest: LatestIngest; conflict: boolean } = {
    latest: { format_version: 1, slug: "demo", status: "none", terminal: false },
    conflict: false,
  };
  const fetchImpl: typeof fetch = async (input, init) => {
    const req = input instanceof Request ? input : null;
    const url = new URL(
      typeof input === "string" || input instanceof URL
        ? String(input)
        : (req?.url ?? ""),
      "http://127.0.0.1",
    );
    const method = (init?.method ?? req?.method ?? "GET").toUpperCase();
    if (method === "POST" && url.pathname === "/api/v1/notebooks/demo/ingest") {
      if (state.conflict) {
        return jsonResponse(
          {
            detail:
              "an ingest is already in flight for notebook 'demo' — wait "
              + "for it to finish before triggering another",
          },
          409,
        );
      }
      state.latest = {
        format_version: 1,
        slug: "demo",
        status: "running",
        terminal: false,
        run_id: 7,
        started_at: "2026-07-04T15:00:00+00:00",
      };
      return jsonResponse(
        {
          format_version: 1,
          slug: "demo",
          run_id: 7,
          status: "running",
          started_at: "2026-07-04T15:00:00+00:00",
        },
        202,
      );
    }
    if (
      method === "GET" &&
      url.pathname === "/api/v1/notebooks/demo/ingest/latest"
    ) {
      return jsonResponse(state.latest as unknown as Record<string, unknown>);
    }
    return jsonResponse({ error: "not_mocked", path: url.pathname }, 404);
  };
  return { fetchImpl, state };
}

/** Scriptable EventSource double. */
class FakeEventSource implements EventSourceLike {
  static instances: FakeEventSource[] = [];
  closed = false;
  onerror: ((this: unknown, ev: Event) => unknown) | null = null;
  private listeners: Record<string, ((ev: MessageEvent) => void)[]> = {};

  constructor(public url: string) {
    FakeEventSource.instances.push(this);
  }

  addEventListener(type: string, l: (ev: MessageEvent) => void) {
    (this.listeners[type] ??= []).push(l);
  }

  close() {
    this.closed = true;
  }

  emit(type: string, payload: unknown) {
    for (const l of this.listeners[type] ?? []) {
      l({ data: JSON.stringify(payload) } as MessageEvent);
    }
  }

  fail() {
    this.onerror?.call(undefined, new Event("error"));
  }
}

function renderPanel(
  fetchImpl: typeof fetch,
  opts: {
    sse?: boolean;
    onRunFinished?: () => void;
  } = {},
) {
  FakeEventSource.instances = [];
  const factory =
    opts.sse === false ? () => null : (url: string) => new FakeEventSource(url);
  const view = render(
    <ApiProvider client={makeClient(fetchImpl, "http://127.0.0.1")}>
      <IngestPanel
        slug="demo"
        notebookKind="arxiv"
        onRunFinished={opts.onRunFinished}
        eventSourceFactory={factory}
        pollIntervalMs={15}
      />
    </ApiProvider>,
  );
  return { view, es: () => FakeEventSource.instances[0] };
}

const stageRow = (stage: string) =>
  document.querySelector(`[data-stage="${stage}"]`);

describe("IngestPanel", () => {
  it("SSE stage events advance the stepper to a succeeded run", async () => {
    const { fetchImpl, state } = ingestServer();
    let finished = 0;
    const { es } = renderPanel(fetchImpl, {
      onRunFinished: () => (finished += 1),
    });
    await screen.findByTestId("ingest-status-badge");
    es().emit("ready", { topics: ["ingest"], cursors: { ingest: 0 } });

    fireEvent.click(screen.getByTestId("ingest-trigger"));
    await waitFor(() =>
      expect(screen.getByTestId("ingest-status-badge").textContent).toBe(
        "running",
      ),
    );
    expect(screen.getByTestId("ingest-transport").textContent).toBe(
      "live stage events (SSE)",
    );

    es().emit("ingest", {
      kind: "ingest", slug: "demo", stage: "preflight",
      phase: "finished", run_id: 7, seq: 1,
    });
    await waitFor(() =>
      expect(stageRow("preflight")?.getAttribute("data-state")).toBe("finished"),
    );
    // Foreign-slug events are ignored.
    es().emit("ingest", {
      kind: "ingest", slug: "other", stage: "chunk",
      phase: "failed", run_id: 9, seq: 2,
    });
    es().emit("ingest", {
      kind: "ingest", slug: "demo", stage: "chunk",
      phase: "started", run_id: 7, seq: 3,
    });
    await waitFor(() =>
      expect(stageRow("chunk")?.getAttribute("data-state")).toBe("started"),
    );
    expect(stageRow("chunk")?.textContent).toContain("running");

    // Run completes: terminal row lands, run event prompts the poll.
    state.latest = {
      format_version: 1, slug: "demo", status: "succeeded", terminal: true,
      run_id: 7, started_at: "2026-07-04T15:00:00+00:00",
      finished_at: "2026-07-04T15:00:09+00:00", exit_code: 0,
    };
    es().emit("ingest", {
      kind: "ingest", slug: "demo", stage: "chunk",
      phase: "finished", run_id: 7, seq: 4,
    });
    es().emit("ingest", {
      kind: "ingest", slug: "demo", stage: "run",
      phase: "finished", run_id: 7, seq: 5,
    });
    await waitFor(() =>
      expect(screen.getByTestId("ingest-status-badge").textContent).toBe(
        "succeeded",
      ),
    );
    await waitFor(() =>
      expect(screen.getByTestId("ingest-line").textContent).toBe(
        "Ingest run 7 succeeded.",
      ),
    );
    expect(finished).toBe(1);
    // Stepper retained its final states.
    expect(stageRow("chunk")?.getAttribute("data-state")).toBe("finished");
  });

  it("pins a failed run at the failing stage with the stderr tail", async () => {
    const { fetchImpl, state } = ingestServer();
    const { es } = renderPanel(fetchImpl);
    await screen.findByTestId("ingest-status-badge");
    es().emit("ready", { topics: ["ingest"], cursors: { ingest: 0 } });

    fireEvent.click(screen.getByTestId("ingest-trigger"));
    await waitFor(() =>
      expect(screen.getByTestId("ingest-status-badge").textContent).toBe(
        "running",
      ),
    );
    es().emit("ingest", {
      kind: "ingest", slug: "demo", stage: "preflight",
      phase: "finished", run_id: 7, seq: 1,
    });
    es().emit("ingest", {
      kind: "ingest", slug: "demo", stage: "embed",
      phase: "failed", run_id: 7, seq: 2,
    });
    state.latest = {
      format_version: 1, slug: "demo", status: "failed", terminal: true,
      run_id: 7, exit_code: 1,
      stderr_tail: "RuntimeError: BGE-M3 embed batch failed",
    };
    es().emit("ingest", {
      kind: "ingest", slug: "demo", stage: "run",
      phase: "failed", run_id: 7, seq: 3,
    });

    await waitFor(() =>
      expect(screen.getByTestId("ingest-status-badge").textContent).toBe(
        "failed",
      ),
    );
    expect(screen.getByTestId("ingest-failure").textContent).toContain(
      "failed at the embed stage",
    );
    expect(screen.getByTestId("ingest-stderr").textContent).toContain(
      "BGE-M3 embed batch failed",
    );
    expect(stageRow("embed")?.getAttribute("data-state")).toBe("failed");
  });

  it("falls back to the labeled tri-state poll when SSE is absent", async () => {
    const { fetchImpl, state } = ingestServer();
    renderPanel(fetchImpl, { sse: false });
    await screen.findByTestId("ingest-status-badge");

    fireEvent.click(screen.getByTestId("ingest-trigger"));
    await waitFor(() =>
      expect(screen.getByTestId("ingest-status-badge").textContent).toBe(
        "running",
      ),
    );
    expect(screen.getByTestId("ingest-transport").textContent).toBe(
      "polling /ingest/latest every 2 s",
    );
    expect(screen.getByTestId("stepper-fallback").textContent).toContain(
      "Stage events unavailable",
    );
    expect(screen.queryByTestId("ingest-stepper")).toBeNull();

    state.latest = {
      format_version: 1, slug: "demo", status: "succeeded", terminal: true,
      run_id: 7, exit_code: 0,
    };
    await waitFor(() =>
      expect(screen.getByTestId("ingest-status-badge").textContent).toBe(
        "succeeded",
      ),
    );
    await waitFor(() =>
      expect(screen.getByTestId("ingest-line").textContent).toBe(
        "Ingest run 7 succeeded.",
      ),
    );
  });

  it('normalizes the wire "success" status to the canonical "succeeded"', async () => {
    // Live-E2E find: the m9 store persists INGEST_STATUS_SUCCESS =
    // "success" and api_v1 passes the column through verbatim. The SPA
    // keys badge class + announce copy on "succeeded"; the poll seam
    // must normalize or a real successful run renders an unkeyed badge
    // and a wrong announce line. Verified to FAIL without the
    // useIngestProgress normalization.
    const { fetchImpl, state } = ingestServer();
    let finished = 0;
    renderPanel(fetchImpl, { sse: false, onRunFinished: () => (finished += 1) });
    await screen.findByTestId("ingest-status-badge");

    fireEvent.click(screen.getByTestId("ingest-trigger"));
    await waitFor(() =>
      expect(screen.getByTestId("ingest-status-badge").textContent).toBe(
        "running",
      ),
    );

    state.latest = {
      format_version: 1, slug: "demo", status: "success", terminal: true,
      run_id: 7, exit_code: 0,
    };
    await waitFor(() =>
      expect(screen.getByTestId("ingest-status-badge").textContent).toBe(
        "succeeded",
      ),
    );
    expect(screen.getByTestId("ingest-status-badge").className).toContain(
      "badge-ok",
    );
    await waitFor(() =>
      expect(screen.getByTestId("ingest-line").textContent).toBe(
        "Ingest run 7 succeeded.",
      ),
    );
    expect(finished).toBe(1);
  });

  it("falls back when the stream errors (404 on the A1 spine)", async () => {
    const { fetchImpl } = ingestServer();
    const { es } = renderPanel(fetchImpl);
    await screen.findByTestId("ingest-status-badge");
    es().fail();

    fireEvent.click(screen.getByTestId("ingest-trigger"));
    await waitFor(() =>
      expect(screen.getByTestId("ingest-transport").textContent).toBe(
        "polling /ingest/latest every 2 s",
      ),
    );
    expect(es().closed).toBe(true);
  });

  it("surfaces the 409 already-in-flight detail verbatim", async () => {
    const { fetchImpl, state } = ingestServer();
    state.conflict = true;
    renderPanel(fetchImpl);
    await screen.findByTestId("ingest-status-badge");

    fireEvent.click(screen.getByTestId("ingest-trigger"));
    await waitFor(() =>
      expect(screen.getByTestId("ingest-line").textContent).toContain(
        "already in flight",
      ),
    );
    expect(screen.getByTestId("ingest-status-badge").textContent).toBe("none");
  });

  it("does not announce a stale terminal run found at mount", async () => {
    const { fetchImpl, state } = ingestServer();
    state.latest = {
      format_version: 1, slug: "demo", status: "succeeded", terminal: true,
      run_id: 3, exit_code: 0,
    };
    renderPanel(fetchImpl);
    await waitFor(() =>
      expect(screen.getByTestId("ingest-status-badge").textContent).toBe(
        "succeeded",
      ),
    );
    // History, not news: the live line stays empty.
    expect(screen.getByTestId("ingest-line").textContent).toBe("");
  });
});
