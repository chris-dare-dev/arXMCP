/**
 * makeGraphApi: the two-layer honesty contract — transport
 * (ok / unavailable-on-route-absent / error) around the a45 envelope,
 * which itself carries the graph_status present/absent/unavailable
 * degradation vocabulary verbatim from the MCP tool.
 */
import { describe, expect, it } from "vitest";
import { makeGraphApi } from "./graph";
import { jsonResponse } from "./mock";

function recordingFetch(
  respond: (url: URL) => Response,
): { fetchImpl: typeof fetch; urls: URL[] } {
  const urls: URL[] = [];
  const fetchImpl: typeof fetch = async (input) => {
    const url = new URL(String(input), "http://127.0.0.1");
    urls.push(url);
    return respond(url);
  };
  return { fetchImpl, urls };
}

const BODY = {
  format_version: 1,
  slug: "bridgeland-stability",
  paper_id: "1203.4613",
  direction: "cites" as const,
  depth: 1,
  limit: 50,
  graph_status: "present" as const,
  neighbors: [
    {
      chunk_id: "0708.2247#stmt-0001",
      paper_id: "0708.2247",
      edge_kind: "cites",
      hop_distance: 1,
      source: "openAlex",
      confidence: 1.0,
    },
  ],
};

describe("makeGraphApi", () => {
  it("passes the a45 envelope through on 200 and builds the query", async () => {
    const { fetchImpl, urls } = recordingFetch(() => jsonResponse(BODY));
    const api = makeGraphApi(fetchImpl);
    const result = await api.neighbors("bridgeland-stability", {
      paper_id: "1203.4613",
      direction: "cites",
      depth: 1,
      limit: 50,
    });
    expect(result.kind).toBe("ok");
    if (result.kind === "ok") {
      expect(result.body.graph_status).toBe("present");
      expect(result.body.neighbors[0].paper_id).toBe("0708.2247");
      expect(result.body.neighbors[0].chunk_id).toContain("#");
    }
    expect(urls[0].pathname).toBe(
      "/api/v1/notebooks/bridgeland-stability/graph/neighbors",
    );
    expect(urls[0].searchParams.get("paper_id")).toBe("1203.4613");
    expect(urls[0].searchParams.get("direction")).toBe("cites");
    expect(urls[0].searchParams.get("depth")).toBe("1");
    expect(urls[0].searchParams.get("limit")).toBe("50");
  });

  it("omits optional params so the server defaults apply", async () => {
    const { fetchImpl, urls } = recordingFetch(() => jsonResponse(BODY));
    await makeGraphApi(fetchImpl).neighbors("bridgeland-stability", {
      paper_id: "1203.4613",
    });
    expect(urls[0].searchParams.has("direction")).toBe(false);
    expect(urls[0].searchParams.has("depth")).toBe(false);
    expect(urls[0].searchParams.has("limit")).toBe(false);
  });

  it("keeps the degraded pair an OK result (absent/unavailable are data)", async () => {
    const { fetchImpl } = recordingFetch(() =>
      jsonResponse({ ...BODY, graph_status: "absent", neighbors: [] }),
    );
    const result = await makeGraphApi(fetchImpl).neighbors(
      "bridgeland-stability",
      { paper_id: "1203.4613" },
    );
    expect(result.kind).toBe("ok");
    if (result.kind === "ok") {
      expect(result.body.graph_status).toBe("absent");
      expect(result.body.neighbors).toEqual([]);
    }
  });

  it("maps the route-absent 404 to unavailable, a named 404 to error", async () => {
    const routeAbsent = makeGraphApi(
      recordingFetch(() => jsonResponse({ detail: "Not Found" }, 404)).fetchImpl,
    );
    expect(
      (
        await routeAbsent.neighbors("bridgeland-stability", {
          paper_id: "1203.4613",
        })
      ).kind,
    ).toBe("unavailable");

    const unknownNotebook = makeGraphApi(
      recordingFetch(() =>
        jsonResponse({ detail: "notebook 'nope' not found" }, 404),
      ).fetchImpl,
    );
    const result = await unknownNotebook.neighbors("nope", {
      paper_id: "1203.4613",
    });
    expect(result.kind).toBe("error");
    if (result.kind === "error") expect(result.detail).toContain("nope");
  });

  it("surfaces the 422 detail for an invalid paper_id", async () => {
    const api = makeGraphApi(
      recordingFetch(() =>
        jsonResponse(
          { detail: "paper_id 'x' does not match the arXiv id format" },
          422,
        ),
      ).fetchImpl,
    );
    const result = await api.neighbors("bridgeland-stability", { paper_id: "x" });
    expect(result.kind).toBe("error");
    if (result.kind === "error") expect(result.detail).toContain("arXiv id format");
  });

  it("maps a thrown fetch to error, never an exception", async () => {
    const api = makeGraphApi(async () => {
      throw new TypeError("network down");
    });
    expect(
      (await api.neighbors("bridgeland-stability", { paper_id: "1203.4613" }))
        .kind,
    ).toBe("error");
  });
});
