/**
 * Notebook management flows, end-to-end at the component tier: a
 * stateful in-memory /api/v1 (mirroring the real handlers' status
 * codes and bodies) drives the REAL pages through the REAL router —
 * create, rename, topic (optimistic + revert), discover→confirm,
 * remove-paper, delete. No live server, no network.
 */
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { describe, expect, it } from "vitest";
import { ApiProvider } from "../../api/ApiProvider";
import { makeClient } from "../../api/client";
import {
  FIXTURE_DISCOVER,
  FIXTURE_HEALTH,
  FIXTURE_NOTEBOOKS,
  FIXTURE_PAPERS,
  jsonResponse,
  pageEnvelope,
} from "../../api/mock";
import type { NotebookRow, PaperRow } from "../../api/types";
import { NotebooksPage } from "../NotebooksPage";
import { NotebookDetailPage } from "./DetailPage";

/** In-memory /api/v1 mirroring the real handlers' contracts. */
function statefulServer() {
  const notebooks: NotebookRow[] = structuredClone(FIXTURE_NOTEBOOKS);
  const papers: Record<string, PaperRow[]> = structuredClone(FIXTURE_PAPERS);
  const health = structuredClone(FIXTURE_HEALTH);

  const fetchImpl: typeof fetch = async (input, init) => {
    const req = input instanceof Request ? input : null;
    const url = new URL(
      typeof input === "string" || input instanceof URL ? String(input) : req?.url ?? "",
      "http://127.0.0.1",
    );
    const method = (init?.method ?? req?.method ?? "GET").toUpperCase();
    const path = url.pathname;
    const readBody = async (): Promise<Record<string, unknown>> => {
      const text = req !== null ? await req.text() : String(init?.body ?? "{}");
      return JSON.parse(text === "" ? "{}" : text) as Record<string, unknown>;
    };

    if (method === "GET" && path === "/api/v1/notebooks") {
      return jsonResponse(pageEnvelope(notebooks, 500));
    }
    if (method === "POST" && path === "/api/v1/notebooks") {
      const body = await readBody();
      const slug = String(body.slug);
      if (notebooks.some((n) => n.slug === slug)) {
        return jsonResponse({ detail: `notebook slug '${slug}' already exists` }, 409);
      }
      const row: NotebookRow = {
        slug,
        display_name: String(body.display_name ?? ""),
        lancedb_path: `var/arxmcp/notebooks/${slug}/lancedb`,
        created_at: "2026-07-04T12:00:00+00:00",
        notebook_kind: String(body.notebook_kind ?? "arxiv"),
        parse_status: "skipped",
        parse_error: null,
        parsed_html_path: null,
        discovery_category: null,
        description: null,
      };
      notebooks.unshift(row); // created_at DESC ordering
      papers[slug] = [];
      return jsonResponse({ format_version: 1, ...row }, 201);
    }

    const one = path.match(/^\/api\/v1\/notebooks\/([^/]+)$/);
    if (one !== null) {
      const nb = notebooks.find((n) => n.slug === one[1]);
      if (nb === undefined) {
        return jsonResponse({ detail: `notebook '${one[1]}' not found` }, 404);
      }
      if (method === "PATCH") {
        const body = await readBody();
        nb.display_name = String(body.display_name);
        return jsonResponse({
          format_version: 1,
          slug: nb.slug,
          display_name: nb.display_name,
        });
      }
      if (method === "DELETE") {
        notebooks.splice(notebooks.indexOf(nb), 1);
        return new Response(null, { status: 204 });
      }
    }

    const topic = path.match(/^\/api\/v1\/notebooks\/([^/]+)\/topic$/);
    if (topic !== null && method === "PATCH") {
      const nb = notebooks.find((n) => n.slug === topic[1]);
      if (nb === undefined) return jsonResponse({ detail: "not found" }, 404);
      const body = await readBody();
      nb.discovery_category = String(body.discovery_category);
      nb.description = String(body.description);
      return jsonResponse({
        format_version: 1,
        slug: nb.slug,
        discovery_category: nb.discovery_category,
        description: nb.description,
      });
    }

    const discover = path.match(/^\/api\/v1\/notebooks\/([^/]+)\/discover$/);
    if (discover !== null && method === "POST") {
      const nb = notebooks.find((n) => n.slug === discover[1]);
      if (nb === undefined) return jsonResponse({ detail: "not found" }, 404);
      if (nb.discovery_category === null || nb.discovery_category === "") {
        return jsonResponse(
          { detail: `notebook '${nb.slug}' has no discovery_category configured` },
          422,
        );
      }
      return jsonResponse({
        format_version: 1,
        slug: nb.slug,
        candidates: FIXTURE_DISCOVER,
        count: FIXTURE_DISCOVER.length,
      });
    }

    const paperOne = path.match(/^\/api\/v1\/notebooks\/([^/]+)\/papers\/(.+)$/);
    if (paperOne !== null && method === "DELETE") {
      const rows = papers[paperOne[1]] ?? [];
      const idx = rows.findIndex((p) => p.paper_id === decodeURIComponent(paperOne[2]));
      if (idx === -1) return jsonResponse({ detail: "paper not in notebook" }, 404);
      rows.splice(idx, 1);
      return new Response(null, { status: 204 });
    }

    const papersCol = path.match(/^\/api\/v1\/notebooks\/([^/]+)\/papers$/);
    if (papersCol !== null) {
      const rows = papers[papersCol[1]];
      if (rows === undefined) return jsonResponse({ detail: "not found" }, 404);
      if (method === "GET") return jsonResponse(pageEnvelope(rows, 500));
      if (method === "POST") {
        const body = await readBody();
        const m = String(body.arxiv_url).match(/\/abs\/(.+)$/);
        if (m === null) return jsonResponse({ detail: "not an arXiv abs URL" }, 422);
        if (rows.some((p) => p.paper_id === m[1])) {
          return jsonResponse({ detail: `paper ${m[1]} already in notebook` }, 409);
        }
        rows.unshift({ paper_id: m[1], added_at: "2026-07-04T12:01:00+00:00" });
        return jsonResponse(
          { format_version: 1, slug: papersCol[1], paper_id: m[1] },
          201,
        );
      }
    }

    const ingestLatest = path.match(
      /^\/api\/v1\/notebooks\/([^/]+)\/ingest\/latest$/,
    );
    if (ingestLatest !== null && method === "GET") {
      // No runs in the component-flows fixture world (the ingest
      // stepper has its own suite: IngestPanel.test.tsx).
      return jsonResponse({
        format_version: 1,
        slug: ingestLatest[1],
        status: "none",
        terminal: false,
      });
    }

    const healthGet = path.match(/^\/api\/v1\/notebooks\/([^/]+)\/health$/);
    if (healthGet !== null && method === "GET") {
      const body = health[healthGet[1]];
      return body !== undefined
        ? jsonResponse(body)
        : jsonResponse(
            {
              format_version: 1,
              slug: healthGet[1],
              status: "no_marker",
              marker_chunk_count: null,
              actual_chunk_count: null,
              marker_paper_count: null,
              actual_paper_count: null,
              drift: null,
              corpus_version: null,
              detail: "no corpus-version.json; run `make ingest` first",
            },
            200,
          );
    }

    return jsonResponse({ error: "not_mocked", path, method }, 404);
  };

  return { fetchImpl, notebooks, papers };
}

function renderApp(fetchImpl: typeof fetch, initialPath: string) {
  return render(
    <ApiProvider client={makeClient(fetchImpl, "http://127.0.0.1")}>
      <MemoryRouter initialEntries={[initialPath]}>
        <Routes>
          <Route path="/" element={<NotebooksPage />} />
          <Route path="/notebooks/:slug" element={<NotebookDetailPage />} />
        </Routes>
      </MemoryRouter>
    </ApiProvider>,
  );
}

describe("create notebook (index inline form)", () => {
  it("creates, announces, and lists the new notebook", async () => {
    const { fetchImpl } = statefulServer();
    renderApp(fetchImpl, "/");
    await screen.findByText("2 notebooks");

    fireEvent.change(screen.getByLabelText("slug"), {
      target: { value: "spectral-forms" },
    });
    fireEvent.change(screen.getByLabelText("display name"), {
      target: { value: "Spectral forms" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Create notebook" }));

    expect((await screen.findByTestId("create-status")).textContent).toBe(
      "Notebook spectral-forms created.",
    );
    await screen.findByText("3 notebooks");
    expect(screen.getByRole("link", { name: "Spectral forms" })).toBeTruthy();
  });

  it("surfaces the 409 duplicate-slug detail verbatim", async () => {
    const { fetchImpl } = statefulServer();
    renderApp(fetchImpl, "/");
    await screen.findByText("2 notebooks");

    fireEvent.change(screen.getByLabelText("slug"), {
      target: { value: "bridgeland-stability" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Create notebook" }));

    expect((await screen.findByTestId("create-status")).textContent).toContain(
      "already exists",
    );
  });
});

describe("rename (detail header)", () => {
  it("saves and echoes the stored display name", async () => {
    const { fetchImpl } = statefulServer();
    renderApp(fetchImpl, "/notebooks/bridgeland-stability");
    await screen.findByTestId("detail-title");

    fireEvent.click(screen.getByRole("button", { name: "Rename" }));
    fireEvent.change(screen.getByLabelText("display name"), {
      target: { value: "Bridgeland stability conditions" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));

    expect((await screen.findByTestId("rename-status")).textContent).toBe(
      "Display name saved.",
    );
    expect(screen.getByTestId("detail-title").textContent).toBe(
      "Bridgeland stability conditions",
    );
  });
});

describe("topic editor (optimistic)", () => {
  it("applies the edit immediately and confirms via aria-live", async () => {
    const { fetchImpl } = statefulServer();
    renderApp(fetchImpl, "/notebooks/bridgeland-stability");
    await screen.findByTestId("detail-title");

    fireEvent.click(screen.getByRole("button", { name: "Edit topic" }));
    fireEvent.change(screen.getByLabelText("category"), {
      target: { value: "hep-th" },
    });
    fireEvent.change(screen.getByLabelText("description"), {
      target: { value: "Topological strings" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save topic" }));

    await waitFor(() =>
      expect(screen.getByTestId("topic-status").textContent).toBe("Topic saved."),
    );
    // Header prose + topic display both update (optimistic patch).
    expect(screen.getAllByText("Topological strings").length).toBeGreaterThan(0);
  });

  it("reverts the optimistic values when the PATCH fails", async () => {
    const { fetchImpl } = statefulServer();
    const failingTopic: typeof fetch = (input, init) => {
      const req = input instanceof Request ? input : null;
      const url = new URL(
        typeof input === "string" || input instanceof URL ? String(input) : req?.url ?? "",
        "http://127.0.0.1",
      );
      const method = (init?.method ?? req?.method ?? "GET").toUpperCase();
      if (method === "PATCH" && url.pathname.endsWith("/topic")) {
        return Promise.resolve(jsonResponse({ detail: "disk on fire" }, 500));
      }
      return fetchImpl(input, init);
    };
    renderApp(failingTopic, "/notebooks/bridgeland-stability");
    await screen.findByTestId("detail-title");

    fireEvent.click(screen.getByRole("button", { name: "Edit topic" }));
    fireEvent.change(screen.getByLabelText("description"), {
      target: { value: "will not stick" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save topic" }));

    await waitFor(() =>
      expect(screen.getByTestId("topic-status").textContent).toBe("disk on fire"),
    );
    // Reverted: the optimistic description is gone, the original stays.
    expect(screen.queryByText("will not stick")).toBeNull();
    expect(
      screen.getAllByText("Stability conditions on derived categories").length,
    ).toBeGreaterThan(0);
  });
});

describe("discovery (propose→confirm)", () => {
  it("proposes candidates and confirms one into the papers table", async () => {
    const { fetchImpl } = statefulServer();
    renderApp(fetchImpl, "/notebooks/fourier-duality");
    await screen.findByTestId("detail-title");
    expect(screen.getByTestId("papers-status").textContent).toBe("0 papers");

    fireEvent.click(screen.getByRole("button", { name: "Run discovery" }));
    expect((await screen.findByTestId("discover-status")).textContent).toContain(
      "2 candidates proposed",
    );
    expect(
      screen.getByText("Stability conditions under Fourier–Mukai transforms"),
    ).toBeTruthy();

    fireEvent.click(
      screen.getAllByRole("button", { name: "Add to notebook" })[0],
    );
    await waitFor(() =>
      expect(screen.getByTestId("discover-status").textContent).toContain(
        "Added 2406.01234",
      ),
    );
    // The confirm refetches the junction table.
    await waitFor(() =>
      expect(screen.getByTestId("papers-status").textContent).toBe("1 paper"),
    );
    expect(screen.getByRole("button", { name: "Added" })).toBeTruthy();
  });

  it("surfaces the 422 unconfigured-topic detail", async () => {
    const { fetchImpl, notebooks } = statefulServer();
    const target = notebooks.find((n) => n.slug === "fourier-duality");
    if (target !== undefined) target.discovery_category = null;
    renderApp(fetchImpl, "/notebooks/fourier-duality");
    await screen.findByTestId("detail-title");

    fireEvent.click(screen.getByRole("button", { name: "Run discovery" }));
    expect((await screen.findByTestId("discover-status")).textContent).toContain(
      "no discovery_category configured",
    );
  });
});

describe("remove paper (two-step)", () => {
  it("removes a junction row after confirm and refetches", async () => {
    const { fetchImpl } = statefulServer();
    renderApp(fetchImpl, "/notebooks/bridgeland-stability");
    await screen.findByTestId("papers-table");
    expect(screen.getByTestId("papers-status").textContent).toBe("2 papers");

    fireEvent.click(screen.getAllByRole("button", { name: "Remove…" })[0]);
    fireEvent.click(screen.getByRole("button", { name: "Confirm remove" }));

    await waitFor(() =>
      expect(screen.getByTestId("papers-action-status").textContent).toContain(
        "Removed 0705.3794",
      ),
    );
    await waitFor(() =>
      expect(screen.getByTestId("papers-status").textContent).toBe("1 paper"),
    );
  });
});

describe("delete notebook (danger zone)", () => {
  it("two-step deletes and returns to a shrunken index", async () => {
    const { fetchImpl } = statefulServer();
    renderApp(fetchImpl, "/notebooks/fourier-duality");
    await screen.findByTestId("detail-title");

    fireEvent.click(screen.getByRole("button", { name: "Delete notebook…" }));
    fireEvent.click(screen.getByRole("button", { name: "Confirm delete" }));

    // navigate("/") lands on the index, which refetches: one left.
    await screen.findByText("1 notebook");
    expect(screen.queryByText("Fourier duality")).toBeNull();
  });
});
