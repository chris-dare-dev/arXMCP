/**
 * Motion wrapper discipline: stagger caps are pure math (test them
 * exactly) and every helper is a no-op under prefers-reduced-motion
 * (trigger-time gate M1 — the CSS clamp is only the backstop).
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { clampStagger } from "./anime";
import {
  STAGGER_MAX_ITEMS,
  STAGGER_MAX_MS,
  STAGGER_MIN_MS,
  STAGGER_TOTAL_MAX_MS,
} from "./tokens";
import { prefersReducedMotion } from "./reducedMotion";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("clampStagger (brief §5.1 caps)", () => {
  it("staggers only the first 8 items", () => {
    const { animatedCount } = clampStagger(200);
    expect(animatedCount).toBe(STAGGER_MAX_ITEMS);
  });

  it("clamps per-item delay into the 40-60ms band", () => {
    expect(clampStagger(5, 5).perItemMs).toBeGreaterThanOrEqual(STAGGER_MIN_MS);
    expect(clampStagger(5, 500).perItemMs).toBeLessThanOrEqual(STAGGER_MAX_MS);
  });

  it("keeps the whole sequence <= 600ms", () => {
    for (const n of [1, 2, 8, 50, 1000]) {
      expect(clampStagger(n, STAGGER_MAX_MS).totalMs).toBeLessThanOrEqual(
        STAGGER_TOTAL_MAX_MS,
      );
    }
  });

  it("animates a short list fully", () => {
    const { animatedCount, totalMs } = clampStagger(3);
    expect(animatedCount).toBe(3);
    expect(totalMs).toBe(2 * clampStagger(3).perItemMs);
  });
});

describe("reduced-motion trigger-time gate", () => {
  it("reports reduced when the OS asks for it", () => {
    vi.stubGlobal("matchMedia", (q: string) => ({
      matches: q.includes("prefers-reduced-motion"),
      addEventListener: () => {},
      removeEventListener: () => {},
    }));
    expect(prefersReducedMotion()).toBe(true);
  });

  it("stays still when no media-query surface exists (never guess)", () => {
    vi.stubGlobal("matchMedia", undefined);
    expect(prefersReducedMotion()).toBe(true);
  });

  it("reports full motion only on an explicit no-preference signal", () => {
    vi.stubGlobal("matchMedia", () => ({
      matches: false,
      addEventListener: () => {},
      removeEventListener: () => {},
    }));
    expect(prefersReducedMotion()).toBe(false);
  });
});
