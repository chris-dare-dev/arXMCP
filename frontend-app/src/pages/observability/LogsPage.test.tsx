/**
 * Logs surface: tail render + closed-set facets with live counts and
 * zero-count dimming, pause/resume with the "N new lines" pill (WCAG
 * 2.2.2), consecutive-duplicate collapse, the line inspector (sorted-
 * key JSON + redaction notice + cross-surface chips), SSE gap
 * markers, and the honest A1-spine unavailable state.
 */
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it } from "vitest";
import { ObsProvider } from "../../api/ObsProvider";
import type { ObsApi } from "../../api/obs";
import { LogsPage } from "./LogsPage";
import { FakeEventSource, makeFakeObs, T0 } from "./testDoubles";

function renderLogs(
  api: ObsApi,
  { sse = true, url = "/logs" }: { sse?: boolean; url?: string } = {},
) {
  FakeEventSource.reset();
  const factory = sse ? (u: string) => new FakeEventSource(u) : () => null;
  const view = render(
    <ObsProvider api={api}>
      <MemoryRouter initialEntries={[url]}>
        <LogsPage eventSourceFactory={factory} pollIntervalMs={20} />
      </MemoryRouter>
    </ObsProvider>,
  );
  return { view, es: () => FakeEventSource.instances[0] };
}

async function waitLoaded() {
  await waitFor(() =>
    expect(screen.getByTestId("logs-status").textContent).toContain("shown"),
  );
}

describe("LogsPage", () => {
  beforeEach(() => FakeEventSource.reset());

  it("renders the tail chronologically with level colors and collapse", async () => {
    const { api } = makeFakeObs();
    renderLogs(api);
    await waitLoaded();
    const rows = screen.getAllByTestId("log-row");
    // 7 fixture records; the 3 identical readyz probes collapse to 1.
    expect(rows).toHaveLength(5);
    expect(rows[0].textContent).toContain("search_papers served");
    expect(rows[3].textContent).toContain("latexml conversion failed");
    expect(rows[3].className).toContain("log-level-down");
    const collapse = screen.getByTestId("log-collapse");
    expect(collapse.textContent).toBe("×3");
    // Retention banner is honest about the ring.
    expect(screen.getByTestId("logs-retention").textContent).toContain(
      "in-memory ring",
    );
  });

  it("facets over the closed field set with live counts; zero-count chips dim, never vanish", async () => {
    const { api } = makeFakeObs();
    renderLogs(api);
    await waitLoaded();

    const levelGroup = screen.getByTestId("facet-level");
    const errorChip = Array.from(
      levelGroup.querySelectorAll("button"),
    ).find((b) => b.textContent?.startsWith("ERROR"));
    expect(errorChip).toBeDefined();
    fireEvent.click(errorChip!);

    await waitFor(() =>
      expect(screen.getAllByTestId("log-row")).toHaveLength(1),
    );
    expect(screen.getAllByTestId("log-row")[0].textContent).toContain(
      "latexml conversion failed",
    );

    // Under the ERROR filter the sketcher role facet counts zero
    // matches — the chip dims (disabled) but is still rendered.
    const roleGroup = screen.getByTestId("facet-role");
    const sketcherChip = Array.from(
      roleGroup.querySelectorAll<HTMLButtonElement>("button"),
    ).find((b) => b.textContent?.startsWith("sketcher"));
    expect(sketcherChip).toBeDefined();
    expect(sketcherChip!.textContent).toContain("0");
    expect(sketcherChip!.disabled).toBe(true);

    // Toggle ERROR off: full tail returns.
    fireEvent.click(errorChip!);
    await waitFor(() =>
      expect(screen.getAllByTestId("log-row")).toHaveLength(5),
    );
  });

  it("initializes facets from the URL (cross-surface navigation)", async () => {
    const { api } = makeFakeObs();
    renderLogs(api, { url: "/logs?session=a1b2c3d4e5f60718" });
    await waitLoaded();
    const rows = screen.getAllByTestId("log-row");
    expect(rows).toHaveLength(2);
  });

  it("pauses the tail, counts new lines on the pill, resumes to them", async () => {
    const { api } = makeFakeObs();
    const { es } = renderLogs(api);
    await waitLoaded();
    es().emit("ready", {
      topics: ["logs"],
      cursors: { logs: 7, requests: 0, ingest: 0 },
    });
    await waitFor(() =>
      expect(screen.getByTestId("logs-status").textContent).toContain(
        "live (SSE)",
      ),
    );

    fireEvent.click(screen.getByTestId("logs-pause"));
    expect(screen.getByTestId("logs-status").textContent).toContain("paused");

    es().emit("logs", {
      seq: 8, ts: T0 + 8, level: "INFO", name: "server.tools",
      message: "find_equation served", tool: "find_equation",
    });
    es().emit("logs", {
      seq: 9, ts: T0 + 9, level: "INFO", name: "server.tools",
      message: "get_paper served", tool: "get_paper",
    });

    // Display is frozen; the pill counts what arrived.
    const pill = await screen.findByTestId("logs-pill");
    expect(pill.textContent).toContain("2 new lines");
    expect(
      screen.queryByText(/find_equation served/),
    ).toBeNull();

    fireEvent.click(pill);
    await waitFor(() =>
      expect(screen.getByText(/get_paper served/)).toBeDefined(),
    );
    expect(screen.queryByTestId("logs-pill")).toBeNull();
    expect(screen.getByTestId("logs-status").textContent).toContain("following");
  });

  it("opens the line inspector with sorted-key JSON, redaction notice and cross-links", async () => {
    const { api } = makeFakeObs();
    renderLogs(api);
    await waitLoaded();
    fireEvent.click(screen.getAllByTestId("log-row")[0]);
    const inspector = await screen.findByTestId("log-inspector");
    const json = inspector.querySelector(".inspector-json")!.textContent!;
    // Sorted keys: "event" before "level" before "message" before "seq".
    const order = ["event", "level", "message", "seq"].map((k) =>
      json.indexOf(`"${k}"`),
    );
    expect([...order].sort((a, b) => a - b)).toEqual(order);
    expect(order.every((i) => i >= 0)).toBe(true);
    expect(screen.getByTestId("inspector-redaction").textContent).toContain(
      "redacted at source",
    );
    const sessionLink = inspector.querySelector("a")!;
    expect(sessionLink.getAttribute("href")).toContain(
      "/requests?session=a1b2c3d4e5f60718",
    );
  });

  it("renders an explicit gap marker on a gap frame", async () => {
    const { api } = makeFakeObs();
    const { es } = renderLogs(api);
    await waitLoaded();
    es().emit("ready", { topics: ["logs"], cursors: { logs: 7 } });
    es().emit("gap", { dropped: 12 });
    const gap = await screen.findByTestId("logs-gap");
    expect(gap.textContent).toContain("12 records dropped");
  });

  it("degrades to polling when the stream errors and shows the banner", async () => {
    const { api, world } = makeFakeObs();
    const { es } = renderLogs(api);
    await waitLoaded();
    es().fail();
    await screen.findByTestId("logs-stream-banner");
    expect(es().closed).toBe(true);
    // The since_seq poll picks up a fresh record without SSE.
    world.logs.push({
      seq: 8, ts: T0 + 8, level: "INFO", name: "server.tools",
      message: "poll-only record",
    });
    await waitFor(() =>
      expect(screen.getByText(/poll-only record/)).toBeDefined(),
    );
  });

  it("states the A1-spine unavailable case honestly", async () => {
    const { api } = makeFakeObs({ unavailable: true });
    renderLogs(api, { sse: false });
    const empty = await screen.findByTestId("logs-unavailable");
    expect(empty.textContent).toContain("GET /api/v1/logs/tail");
    expect(empty.textContent).toContain("arx-a23");
    expect(screen.queryByTestId("log-row")).toBeNull();
  });
});
