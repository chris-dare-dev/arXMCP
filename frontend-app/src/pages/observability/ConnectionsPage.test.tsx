/**
 * Connections surface: the one-sentence trust header, the session
 * roster (activity dots, cap meters incl. the exhausted state, the
 * hourly window, cross-links), the copyable connect snippet in the
 * empty state, and the ingest stage-event history with slug facet.
 */
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it } from "vitest";
import { ObsProvider } from "../../api/ObsProvider";
import type { ObsApi } from "../../api/obs";
import { ConnectionsPage } from "./ConnectionsPage";
import { FakeEventSource, makeFakeObs, T0 } from "./testDoubles";

function renderConnections(
  api: ObsApi,
  { sse = true, url = "/connections" }: { sse?: boolean; url?: string } = {},
) {
  FakeEventSource.reset();
  const factory = sse ? (u: string) => new FakeEventSource(u) : () => null;
  const view = render(
    <ObsProvider api={api}>
      <MemoryRouter initialEntries={[url]}>
        <ConnectionsPage
          eventSourceFactory={factory}
          pollIntervalMs={20}
          sessionsPollMs={20}
          now={() => T0 + 60}
        />
      </MemoryRouter>
    </ObsProvider>,
  );
  return { view, es: () => FakeEventSource.instances[0] };
}

describe("ConnectionsPage", () => {
  beforeEach(() => FakeEventSource.reset());

  it("renders the trust header sentence from /status + sessions", async () => {
    const { api } = makeFakeObs();
    renderConnections(api);
    const header = await screen.findByTestId("trust-header");
    await waitFor(() => expect(header.textContent).toContain("corpus v1690"));
    expect(header.textContent).toContain("ready");
    expect(header.textContent).toContain("2 sessions tracked");
  });

  it("renders the roster with activity dots, cap meters and cross-links", async () => {
    const { api } = makeFakeObs();
    renderConnections(api);
    await screen.findByTestId("session-roster");

    // Fresh session (last_seen 30 s before the injected now): active.
    const fresh = screen.getByTestId("session-a1b2c3d4e5f60718");
    expect(fresh.querySelector(".activity-dot-active")).not.toBeNull();
    // Stale session (an hour old): idle, dimmed row.
    const stale = screen.getByTestId("session-0f1e2d3c4b5a6978");
    expect(stale.querySelector(".activity-dot-active")).toBeNull();
    expect(stale.className).toContain("session-row-idle");

    // Exhausted cap (search 3/3) flips the fill to the down token.
    const exhausted = fresh.querySelector(
      '[data-testid="cap-search_papers"] .cap-meter-fill',
    )!;
    expect(exhausted.className).toContain("cap-meter-fill-exhausted");
    expect(fresh.textContent).toContain("3/3");
    // Healthy cap and the hourly window render honest numbers.
    expect(fresh.textContent).toContain("1/4");
    expect(fresh.textContent).toContain("4/1000");

    // Cross-links carry the session prefix into Logs/Requests.
    const links = Array.from(fresh.querySelectorAll("a")).map((a) =>
      a.getAttribute("href"),
    );
    expect(links).toContain("/logs?session=a1b2c3d4e5f60718");
    expect(links).toContain("/requests?session=a1b2c3d4e5f60718");
  });

  it("teaches the connect header in the empty state with a copy affordance", async () => {
    const { api } = makeFakeObs({ sessions: [] });
    renderConnections(api);
    const empty = await screen.findByTestId("roster-empty");
    expect(screen.getByTestId("connect-snippet").textContent).toBe(
      "Arxmcp-Agent-Role: sketcher",
    );
    expect(empty.textContent).not.toContain("!");
    const copied: string[] = [];
    Object.assign(navigator, {
      clipboard: { writeText: (t: string) => (copied.push(t), Promise.resolve()) },
    });
    fireEvent.click(screen.getByTestId("copy-snippet"));
    await waitFor(() => expect(copied).toContain("Arxmcp-Agent-Role: sketcher"));
  });

  it("renders the ingest history newest-first with failure coloring and slug facet", async () => {
    const { api } = makeFakeObs();
    renderConnections(api);
    await screen.findByTestId("ingest-history-table");
    const rows = screen.getAllByTestId("ingest-history-row");
    expect(rows).toHaveLength(4);
    expect(rows[0].textContent).toContain("mineru");
    expect(rows[0].querySelector(".malformed-note")?.textContent).toBe("failed");
    expect(rows[3].textContent).toContain("preflight");

    const facet = screen.getByTestId("ingest-slug-facet");
    const chip = Array.from(facet.querySelectorAll("button")).find((b) =>
      b.textContent?.startsWith("bridgeland-stability"),
    );
    fireEvent.click(chip!);
    await waitFor(() =>
      expect(screen.getAllByTestId("ingest-history-row")).toHaveLength(3),
    );
  });

  it("appends live ingest stage events from the stream", async () => {
    const { api } = makeFakeObs();
    const { es } = renderConnections(api);
    await screen.findByTestId("ingest-history-table");
    es().emit("ready", { topics: ["ingest"], cursors: { ingest: 4 } });
    es().emit("ingest", {
      seq: 5, ts: T0 + 200, kind: "ingest", slug: "fourier-duality",
      stage: "embed", phase: "started", run_id: 4,
    });
    await waitFor(() =>
      expect(screen.getAllByTestId("ingest-history-row")).toHaveLength(5),
    );
    expect(screen.getAllByTestId("ingest-history-row")[0].textContent).toContain(
      "fourier-duality",
    );
  });

  it("states the A1-spine unavailable case honestly (roster + history)", async () => {
    const { api } = makeFakeObs({ unavailable: true });
    renderConnections(api, { sse: false });
    const roster = await screen.findByTestId("roster-unavailable");
    expect(roster.textContent).toContain("GET /api/v1/sessions");
    await waitFor(() =>
      expect(screen.getByTestId("ingest-history-status").textContent).toContain(
        "unavailable on this server build",
      ),
    );
  });
});
