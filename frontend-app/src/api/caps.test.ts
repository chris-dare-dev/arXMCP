/**
 * makeCapsApi: the three-state contract over the a23 profile CRUD
 * (ok / unavailable-on-route-absent-404 / error), the documented 404
 * disambiguation seam, and the AC-A.10 token discipline (the body the
 * client PUTs never carries a raw token member).
 */
import { describe, expect, it } from "vitest";
import { makeCapsApi, PROFILE_NAME_RE, TOKEN_SHA256_RE } from "./caps";
import { jsonResponse } from "./mock";

function recordingFetch(
  respond: (url: URL, init?: RequestInit) => Response,
): { fetchImpl: typeof fetch; calls: { url: URL; init?: RequestInit }[] } {
  const calls: { url: URL; init?: RequestInit }[] = [];
  const fetchImpl: typeof fetch = async (input, init) => {
    const url = new URL(String(input), "http://127.0.0.1");
    calls.push({ url, init });
    return respond(url, init);
  };
  return { fetchImpl, calls };
}

const PROFILE = {
  name: "default",
  enabled: true,
  token_sha256: null,
  tools: null,
  caps: {},
  notebooks: null,
};

describe("makeCapsApi", () => {
  it("lists the effective profiles on 200", async () => {
    const { fetchImpl, calls } = recordingFetch(() =>
      jsonResponse({ format_version: 1, items: [PROFILE], total: 1 }),
    );
    const api = makeCapsApi(fetchImpl);
    const result = await api.list();
    expect(result.kind).toBe("ok");
    if (result.kind === "ok") {
      expect(result.items[0].name).toBe("default");
      expect(result.total).toBe(1);
    }
    expect(calls[0].url.pathname).toBe("/api/v1/capabilities/profiles");
  });

  it("maps the route-absent 404 to unavailable on every verb (A1 spine)", async () => {
    const { fetchImpl } = recordingFetch(() =>
      jsonResponse({ detail: "Not Found" }, 404),
    );
    const api = makeCapsApi(fetchImpl);
    expect((await api.list()).kind).toBe("unavailable");
    expect((await api.upsert("web", { enabled: true })).kind).toBe("unavailable");
    expect((await api.remove("web")).kind).toBe("unavailable");
  });

  it("keeps a DOMAIN 404 (named detail) an error, not unavailable", async () => {
    const { fetchImpl } = recordingFetch(() =>
      jsonResponse({ detail: "profile 'default' not found" }, 404),
    );
    const api = makeCapsApi(fetchImpl);
    const result = await api.remove("default");
    expect(result.kind).toBe("error");
    if (result.kind === "error") {
      expect(result.detail).toContain("not found");
    }
  });

  it("PUTs the upsert body verbatim — token_sha256 only, never token", async () => {
    const { fetchImpl, calls } = recordingFetch(() =>
      jsonResponse({ format_version: 1, name: "website", result: "upserted" }),
    );
    const api = makeCapsApi(fetchImpl);
    const result = await api.upsert("website", {
      enabled: true,
      token_sha256: "a".repeat(64),
      tools: ["search_papers"],
      caps: { search_papers: 5 },
      notebooks: ["bridgeland-stability"],
    });
    expect(result.kind).toBe("ok");
    expect(calls[0].init?.method).toBe("PUT");
    expect(calls[0].url.pathname).toBe("/api/v1/capabilities/profiles/website");
    const sent = JSON.parse(String(calls[0].init?.body)) as Record<string, unknown>;
    expect(sent.token_sha256).toBe("a".repeat(64));
    expect("token" in sent).toBe(false);
    expect(sent.tools).toEqual(["search_papers"]);
  });

  it("surfaces 422 details (string and pydantic-array shapes)", async () => {
    const apiString = makeCapsApi(
      recordingFetch(() =>
        jsonResponse(
          { detail: "token_sha256 must be a 64-char lowercase hex SHA-256 digest of the token — never the token value itself" },
          422,
        ),
      ).fetchImpl,
    );
    const res = await apiString.upsert("web", { enabled: true });
    expect(res.kind).toBe("error");
    if (res.kind === "error") expect(res.detail).toContain("64-char");

    const apiArray = makeCapsApi(
      recordingFetch(() =>
        jsonResponse({ detail: [{ msg: "Extra inputs are not permitted", loc: ["body", "token"] }] }, 422),
      ).fetchImpl,
    );
    const res2 = await apiArray.upsert("web", { enabled: true });
    expect(res2.kind).toBe("error");
    if (res2.kind === "error") expect(res2.detail).toContain("Extra inputs");
  });

  it("maps a thrown fetch to error, never an exception", async () => {
    const api = makeCapsApi(async () => {
      throw new TypeError("network down");
    });
    expect((await api.list()).kind).toBe("error");
    expect((await api.upsert("x", { enabled: true })).kind).toBe("error");
    expect((await api.remove("x")).kind).toBe("error");
  });

  it("mirrors the server validation regexes for inline form feedback", () => {
    expect(PROFILE_NAME_RE.test("website")).toBe(true);
    expect(PROFILE_NAME_RE.test("web-2")).toBe(true);
    expect(PROFILE_NAME_RE.test("Web")).toBe(false);
    expect(PROFILE_NAME_RE.test("2web")).toBe(false);
    expect(PROFILE_NAME_RE.test("a".repeat(65))).toBe(false);
    expect(TOKEN_SHA256_RE.test("f".repeat(64))).toBe(true);
    expect(TOKEN_SHA256_RE.test("F".repeat(64))).toBe(false);
    expect(TOKEN_SHA256_RE.test("f".repeat(63))).toBe(false);
  });
});
