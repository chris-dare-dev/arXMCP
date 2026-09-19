/**
 * Typed API client over the IF-1 contract (repo-root openapi.json,
 * dumped offline by tools/dump_openapi.py on the stage2/arx-a1 spine).
 *
 * openapi-fetch + the generated `paths` type give compile-time checking
 * of every route/parameter/response the SPA touches. Same-origin only:
 * baseUrl is relative, satisfying connect-src 'self' (AC-B.2) — the
 * SPA is served by the same FastAPI process that serves /api/v1.
 */
import createClient from "openapi-fetch";
import type { paths } from "./schema";

export type ApiClient = ReturnType<typeof createClient<paths>>;

/** Build a client; tests may inject a mock fetch (see mock.ts) and an
 * absolute baseUrl (Node's Request cannot resolve relative URLs — in
 * the browser the relative default keeps everything same-origin). */
export function makeClient(fetchImpl?: typeof fetch, baseUrl = "/"): ApiClient {
  return createClient<paths>({
    baseUrl,
    ...(fetchImpl ? { fetch: fetchImpl } : {}),
  });
}

/** App-wide default client. */
export const api = makeClient();
