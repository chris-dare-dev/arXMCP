/**
 * Shared observability atoms [T] (brief §7.0): cap meter, click-to-
 * filter chips, and UTC time formatting. All telemetry register;
 * status colors appear only on status-bearing elements (CO-4).
 */

/** "HH:MM:SS" UTC from wall-clock seconds — deterministic for fixture
 * timestamps (visual baselines) and unambiguous on a single-operator
 * loopback box. The column header carries the UTC label.
 *
 * Defensive on malformed input (integration hardening): a missing or
 * non-finite ts renders as an em dash instead of throwing — a
 * timestamp formatter must never be able to take down a whole route
 * (pre-fix, a server frame without `ts` crashed the logs/requests
 * pages via RangeError inside React render; the server-side IF-2
 * shape parity fix is the real close, this guard keeps any future
 * drift visible-but-survivable). */
export function fmtClock(ts: number): string {
  if (!Number.isFinite(ts)) return "—";
  return new Date(ts * 1000).toISOString().slice(11, 19);
}

/** Full ISO instant (inspector drawers). Same malformed-input guard
 * as {@link fmtClock}. */
export function fmtIso(ts: number): string {
  if (!Number.isFinite(ts)) return "—";
  return new Date(ts * 1000).toISOString();
}

/** Depleting cap bar: `search_papers 2/3` with remaining as the fill.
 * Accent is the working color; exhausted caps switch to the down
 * status token (status-bearing element, CO-4). Stepwise width changes
 * ride the CSS dur-2 transition; reduced motion is clamped globally. */
export function CapMeter({
  label,
  used,
  limit,
}: {
  label: string;
  used: number;
  limit: number;
}) {
  const remaining = Math.max(limit - used, 0);
  const pct = limit > 0 ? Math.min(used / limit, 1) : 1;
  return (
    <div className="cap-meter reg-telemetry" data-testid={`cap-${label}`}>
      <span className="cap-meter-label">{label}</span>
      <span
        className="cap-meter-track"
        role="meter"
        aria-valuemin={0}
        aria-valuemax={limit}
        aria-valuenow={used}
        aria-label={`${label}: ${used} of ${limit} used`}
      >
        <span
          className={remaining === 0 ? "cap-meter-fill cap-meter-fill-exhausted" : "cap-meter-fill"}
          style={{ width: `${Math.round(pct * 100)}%` }}
        />
      </span>
      <span className="cap-meter-count">
        {used}/{limit}
      </span>
    </div>
  );
}

/** Queryless facet chip (brief §7.4 L2): live count, toggleable,
 * zero-count chips dim (disabled) but never vanish. No query
 * language — the closed field set makes faceting sufficient. */
export function FilterChip({
  value,
  count,
  active,
  onToggle,
}: {
  value: string;
  count: number;
  active: boolean;
  onToggle: () => void;
}) {
  return (
    <button
      type="button"
      className="chip-toggle"
      aria-pressed={active}
      disabled={!active && count === 0}
      onClick={onToggle}
    >
      {value} <span className="chip-count">{count}</span>
    </button>
  );
}

/** Count entry values per facet field over the retained window. */
export function facetCounts<T>(
  items: T[],
  read: (item: T) => string | null | undefined,
): Map<string, number> {
  const counts = new Map<string, number>();
  for (const item of items) {
    const value = read(item);
    if (value === null || value === undefined || value === "") continue;
    counts.set(value, (counts.get(value) ?? 0) + 1);
  }
  return counts;
}
