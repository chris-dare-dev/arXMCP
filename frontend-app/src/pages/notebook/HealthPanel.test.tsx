/**
 * HealthPanel state-matrix tests: the two marker-absent states
 * (no_marker / malformed_marker) that the DetailPage integration
 * tests do not reach, plus the null/loading and endpoint-error lines.
 */
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { HealthResult } from "../../api/types";
import { HealthPanel } from "./HealthPanel";

const base: HealthResult = {
  format_version: 1,
  slug: "s",
  status: "no_marker",
  marker_chunk_count: null,
  actual_chunk_count: null,
  marker_paper_count: null,
  actual_paper_count: null,
  drift: null,
  corpus_version: null,
  detail: "no corpus-version.json; run `make ingest` first",
};

function renderPanel(health: HealthResult | null, healthError: string | null = null) {
  return render(
    <HealthPanel slug="s" health={health} healthError={healthError} onReconciled={() => {}} />,
  );
}

describe("HealthPanel marker-absent states", () => {
  it("no_marker: ops badge, server detail copy, no stat block, no reconcile", () => {
    renderPanel(base);
    expect(screen.getByText("no marker").className).toContain("badge-ops");
    expect(screen.getByTestId("health-sentence").textContent).toContain(
      "run `make ingest` first",
    );
    expect(screen.queryByTestId("stat-block")).toBeNull();
    expect(screen.queryByRole("button")).toBeNull();
  });

  it("malformed_marker: down badge + investigate copy", () => {
    renderPanel({
      ...base,
      status: "malformed_marker",
      detail: "corpus-version.json is malformed; investigate",
    });
    expect(screen.getByText("malformed").className).toContain("badge-down");
    const sentence = screen.getByTestId("health-sentence");
    expect(sentence.className).toContain("malformed-note");
    expect(sentence.textContent).toContain("investigate");
  });

  it("null health without error reads as the in-flight line", () => {
    renderPanel(null);
    expect(screen.getByTestId("health-status").textContent).toContain(
      "Reading corpus-version.json marker…",
    );
  });

  it("endpoint error is surfaced verbatim", () => {
    renderPanel(null, "GET /api/v1/notebooks/s/health failed (503).");
    expect(screen.getByTestId("health-status").textContent).toContain("failed (503)");
  });
});
