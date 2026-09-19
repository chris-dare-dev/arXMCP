/**
 * makeObsApi: envelope pass-through, the three-state result contract
 * (ok / unavailable-on-404 / error), and query-string construction —
 * the seam every observability surface stands on.
 */
import { describe, expect, it } from "vitest";
import { jsonResponse } from "./mock";
import { makeObsApi } from "./obs";

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

describe("makeObsApi", () => {
  it("returns the page envelope on 200", async () => {
    const body = {
      format_version: 1,
      items: [{ seq: 3, ts: 1, tool: "search_papers" }],
      total: 1,
      limit: 100,
      offset: 0,
      latest_seq: 3,
    };
    const { fetchImpl } = recordingFetch(() => jsonResponse(body));
    const api = makeObsApi(fetchImpl);
    const result = await api.requests();
    expect(result.kind).toBe("ok");
    if (result.kind === "ok") {
      expect(result.page.items[0].seq).toBe(3);
      expect(result.page.latest_seq).toBe(3);
    }
  });

  it("maps 404 to unavailable (the A1 spine) and 5xx to error", async () => {
    const api404 = makeObsApi(
      recordingFetch(() => jsonResponse({ detail: "Not Found" }, 404)).fetchImpl,
    );
    expect((await api404.logsTail()).kind).toBe("unavailable");
    expect((await api404.sessions()).kind).toBe("unavailable");

    const api503 = makeObsApi(
      recordingFetch(() => jsonResponse({ detail: "warming" }, 503)).fetchImpl,
    );
    const res = await api503.requests();
    expect(res.kind).toBe("error");
    if (res.kind === "error") expect(res.detail).toContain("503");
  });

  it("maps a thrown fetch to error, never an exception", async () => {
    const api = makeObsApi(async () => {
      throw new TypeError("network down");
    });
    const res = await api.ingestEvents();
    expect(res.kind).toBe("error");
    expect(await api.status()).toBeNull();
  });

  it("extracts corpus_version from the /status health+json checks (warm server)", async () => {
    // Regression: /status returns IETF application/health+json
    // ({status, description, checks}) — NOT a flat {status, corpus_version}.
    // The shared corpus version lives at checks["corpus:version"][0]
    // .observedValue. A raw cast leaves corpus_version undefined, which the
    // Connections C1 trust header rendered as the literal "corpus vundefined"
    // (Stage-3 finding connections-trust-header-renders-corpus-vundefined).
    const warmBody = {
      status: "warn",
      description: "arXMCP MCP server",
      checks: {
        "embedder:status": [{ componentType: "component", status: "pass" }],
        "corpus:version": [
          {
            componentType: "datastore",
            observedValue: 1690,
            observedUnit: "version",
            status: "pass",
          },
        ],
        "notebooks:corpus_versions": [
          { componentType: "datastore", observedValue: { "bridgeland-stability": 1690 }, status: "pass" },
        ],
      },
    };
    const api = makeObsApi(recordingFetch(() => jsonResponse(warmBody)).fetchImpl);
    const status = await api.status();
    expect(status).not.toBeNull();
    expect(status?.status).toBe("warn");
    // The load-bearing assertion: a real number, never undefined/null.
    expect(status?.corpus_version).toBe(1690);
  });

  it("reports corpus_version null (not undefined) when /status omits the corpus check (bootstrap/cold)", async () => {
    // Bootstrap-mode /status (captured live) carries process:uptime +
    // notebooks:corpus_versions but NO corpus:version check. The trust
    // header must degrade to "no corpus version", so status() must yield an
    // explicit null — the strict `!== null` guard in ConnectionsPage then
    // takes the honest branch instead of the "vundefined" one.
    const bootstrapBody = {
      status: "warn",
      description: "arXMCP MCP server",
      checks: {
        "process:uptime": [{ componentType: "system", observedValue: 14.7, status: "pass" }],
        "notebooks:corpus_versions": [{ componentType: "datastore", observedValue: {}, status: "pass" }],
      },
    };
    const api = makeObsApi(recordingFetch(() => jsonResponse(bootstrapBody)).fetchImpl);
    const status = await api.status();
    expect(status).not.toBeNull();
    expect(status?.corpus_version).toBeNull();
  });

  it("tolerates a flat {status, corpus_version} /status body as a fallback", async () => {
    // Some fixtures/deployments still expose the version flat; status()
    // falls back to the top-level field so those keep resolving.
    const api = makeObsApi(
      recordingFetch(() => jsonResponse({ status: "ready", corpus_version: 1517 })).fetchImpl,
    );
    const status = await api.status();
    expect(status?.corpus_version).toBe(1517);
    expect(status?.status).toBe("ready");
  });

  it("builds ring queries (since_seq, level, slug) and omits absent params", async () => {
    const { fetchImpl, urls } = recordingFetch(() =>
      jsonResponse({ format_version: 1, items: [], total: 0, limit: 5, offset: 0 }),
    );
    const api = makeObsApi(fetchImpl);
    await api.logsTail({ limit: 5, since_seq: 40, level: "ERROR" });
    await api.ingestEvents({ slug: "bridgeland-stability" });
    await api.requests();
    expect(urls[0].pathname).toBe("/api/v1/logs/tail");
    expect(urls[0].searchParams.get("limit")).toBe("5");
    expect(urls[0].searchParams.get("since_seq")).toBe("40");
    expect(urls[0].searchParams.get("level")).toBe("ERROR");
    expect(urls[1].pathname).toBe("/api/v1/ingest-events");
    expect(urls[1].searchParams.get("slug")).toBe("bridgeland-stability");
    expect(urls[2].pathname).toBe("/api/v1/requests");
    expect(urls[2].search).toBe("");
  });
});
