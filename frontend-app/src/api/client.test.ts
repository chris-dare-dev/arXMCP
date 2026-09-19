/**
 * Typed client against the mock server (IF-1 decoupling proof:
 * the SPA layer is testable with zero live arXMCP process).
 */
import { describe, expect, it } from "vitest";
import { makeClient } from "./client";
import { FIXTURE_NOTEBOOKS, FIXTURE_STATUS, mockFetch } from "./mock";
import type { NotebookRow, PageEnvelope } from "./types";

// Absolute base: Node's Request rejects relative URLs (browser code
// keeps the relative same-origin default).
const client = makeClient(mockFetch, "http://127.0.0.1");

describe("typed client over mock /api/v1", () => {
  it("lists notebooks in the real _page envelope shape", async () => {
    const { data, error, response } = await client.GET("/api/v1/notebooks");
    expect(error).toBeUndefined();
    expect(response.status).toBe(200);
    const page = data as unknown as PageEnvelope<NotebookRow>;
    expect(page.format_version).toBe(1);
    expect(page.total).toBe(FIXTURE_NOTEBOOKS.length);
    expect(page.items.map((n) => n.slug)).toEqual([
      "bridgeland-stability",
      "fourier-duality",
    ]);
    // Row fields mirror notebooks_store.list_notebooks() exactly.
    for (const row of page.items) {
      expect(row).toHaveProperty("display_name");
      expect(row).toHaveProperty("notebook_kind");
      expect(row).toHaveProperty("parse_status");
      expect(row).toHaveProperty("created_at");
    }
  });

  it("serves /status with corpus_version (the arx-a1 restoration)", async () => {
    const { data, error } = await client.GET("/status");
    expect(error).toBeUndefined();
    expect(data).toMatchObject(FIXTURE_STATUS);
  });

  it("surfaces unmocked routes as errors, not silent successes", async () => {
    const { error, response } = await client.GET("/api/v1/notebooks/{slug}/health", {
      params: { path: { slug: "nope" } },
    });
    expect(response.status).toBe(404);
    expect(error).toBeDefined();
  });
});
