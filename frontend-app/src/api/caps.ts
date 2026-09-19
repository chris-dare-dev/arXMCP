/**
 * Capability-profile API seam (arx-b3, WS-B over WS-A A2).
 *
 * The profile CRUD lives on the arx-a23 branch
 * (server/routes/capabilities.py), NOT on this branch's A1 spine — so
 * it is absent from the IF-1 openapi.json dump and the generated
 * schema.d.ts cannot type it. This module is the hand-maintained twin
 * of that contract (field-for-field match verified against
 * server/routes/capabilities.py on stage2/arx-a23), with the b2/b3
 * degrade discipline: a route-absent 404 is an "unavailable" result,
 * never an exception — the page renders an honest degraded state and
 * needs zero client changes at integration.
 *
 * Token discipline (AC-A.10) is enforced at the TYPE level too: the
 * upsert body has no `token` member — only `token_sha256`. The server
 * rejects a raw token with 422 (`extra="forbid"`); this client never
 * produces one.
 *
 * Same-origin relative URLs only (connect-src 'self', AC-B.2); tests
 * inject a fetch double via makeCapsApi(fetchImpl, base).
 */

/** One effective profile row — the PARSED view the a23 list endpoint
 * serves (synthesized `default` included when the operator has not
 * overridden it, so the operator always sees the policy in force). */
export interface CapabilityProfileRow {
  name: string;
  enabled: boolean;
  /** SHA-256 hex digest of the bearer token; null = token-less
   * (the unauthenticated-loopback profile). Never a token value. */
  token_sha256: string | null;
  /** Tool allowlist; null = all tools; empty = deny-all. */
  tools: string[] | null;
  /** Per-tool per-session caps superseding the built-in constants. */
  caps: Record<string, number>;
  /** Notebook-slug allowlist; null = unscoped. */
  notebooks: string[] | null;
}

/** PUT body (server ProfileUpsert, `extra="forbid"`). Deliberately no
 * `token` member — see the module doc. */
export interface ProfileUpsert {
  enabled: boolean;
  token_sha256?: string;
  tools?: string[];
  caps?: Record<string, number>;
  notebooks?: string[];
}

export type CapsListResult =
  | { kind: "ok"; items: CapabilityProfileRow[]; total: number }
  | { kind: "unavailable" }
  | { kind: "error"; detail: string };

export type CapsMutateResult =
  | { kind: "ok" }
  | { kind: "unavailable" }
  | { kind: "error"; detail: string };

export interface CapsApi {
  list(): Promise<CapsListResult>;
  upsert(name: string, body: ProfileUpsert): Promise<CapsMutateResult>;
  remove(name: string): Promise<CapsMutateResult>;
}

/** Client-side mirrors of the server's validation regexes — used for
 * inline form feedback only; the server remains the authority. */
export const PROFILE_NAME_RE = /^[a-z][a-z0-9-]{0,63}$/;
export const TOKEN_SHA256_RE = /^[0-9a-f]{64}$/;

/** Extract a human-readable detail from a FastAPI error body
 * ({detail: string} or pydantic's {detail: [{msg, ...}]}). */
async function readDetail(res: Response, fallback: string): Promise<string> {
  try {
    const body = (await res.json()) as { detail?: unknown };
    if (typeof body.detail === "string") return body.detail;
    if (Array.isArray(body.detail)) {
      const msgs = body.detail
        .map((d) => (d as { msg?: string }).msg)
        .filter((m): m is string => typeof m === "string");
      if (msgs.length > 0) return msgs.join("; ");
    }
  } catch {
    /* non-JSON error body — fall through */
  }
  return fallback;
}

/** A 404 is ambiguous on this surface: route-absent (A1 spine — the
 * whole capabilities router is missing) vs domain-level (profile not
 * found on DELETE). FastAPI's route-absent body is exactly
 * {"detail": "Not Found"}; the a23 handlers always name the subject
 * in their 404 details. The seam is documented here and pinned by
 * tests on both sides of it. */
async function classify404(res: Response): Promise<CapsMutateResult> {
  const detail = await readDetail(res, "Not Found");
  if (detail === "Not Found") return { kind: "unavailable" };
  return { kind: "error", detail };
}

export function makeCapsApi(fetchImpl?: typeof fetch, base = ""): CapsApi {
  const doFetch: typeof fetch = fetchImpl ?? ((...args) => fetch(...args));
  const root = `${base}/api/v1/capabilities/profiles`;

  return {
    async list(): Promise<CapsListResult> {
      let res: Response;
      try {
        res = await doFetch(root);
      } catch {
        return { kind: "error", detail: "GET profiles failed (network)" };
      }
      if (res.status === 404) return { kind: "unavailable" };
      if (!res.ok) {
        return {
          kind: "error",
          detail: await readDetail(res, `GET profiles failed (${res.status})`),
        };
      }
      try {
        const body = (await res.json()) as {
          items: CapabilityProfileRow[];
          total: number;
        };
        return { kind: "ok", items: body.items, total: body.total };
      } catch {
        return { kind: "error", detail: "GET profiles returned non-JSON" };
      }
    },

    async upsert(name: string, body: ProfileUpsert): Promise<CapsMutateResult> {
      let res: Response;
      try {
        res = await doFetch(`${root}/${encodeURIComponent(name)}`, {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        });
      } catch {
        return { kind: "error", detail: `PUT profile ${name} failed (network)` };
      }
      if (res.status === 404) return classify404(res);
      if (!res.ok) {
        return {
          kind: "error",
          detail: await readDetail(res, `PUT profile ${name} failed (${res.status})`),
        };
      }
      return { kind: "ok" };
    },

    async remove(name: string): Promise<CapsMutateResult> {
      let res: Response;
      try {
        res = await doFetch(`${root}/${encodeURIComponent(name)}`, {
          method: "DELETE",
        });
      } catch {
        return {
          kind: "error",
          detail: `DELETE profile ${name} failed (network)`,
        };
      }
      if (res.status === 404) return classify404(res);
      if (!res.ok) {
        return {
          kind: "error",
          detail: await readDetail(
            res,
            `DELETE profile ${name} failed (${res.status})`,
          ),
        };
      }
      return { kind: "ok" };
    },
  };
}

/** App-wide default (same-origin). */
export const capsApi = makeCapsApi();
