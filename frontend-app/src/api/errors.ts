/**
 * FastAPI error-body reader. /api/v1 errors carry {"detail": string}
 * (HTTPException) or {"detail": [{msg, loc, ...}]} (Pydantic 422).
 * Returns the operator-facing sentence, or null when the body carries
 * nothing usable (caller falls back to a status-code line).
 */
export function errorDetail(error: unknown): string | null {
  if (typeof error !== "object" || error === null || !("detail" in error)) {
    return null;
  }
  const detail = (error as { detail?: unknown }).detail;
  if (typeof detail === "string" && detail !== "") return detail;
  if (Array.isArray(detail)) {
    const msgs = detail.map((item) =>
      typeof item === "object" && item !== null && "msg" in item
        ? String((item as { msg: unknown }).msg)
        : String(item),
    );
    return msgs.length > 0 ? msgs.join("; ") : null;
  }
  return null;
}
