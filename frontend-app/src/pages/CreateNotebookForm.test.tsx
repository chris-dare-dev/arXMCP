/**
 * Regression for the arx-b2 verification finding 2 (fix pass):
 * browsers compile the HTML `pattern` attribute with the RegExp
 * v flag, under which the previous value ([a-z][a-z0-9-]{2,30},
 * unescaped hyphen in the class) was a SyntaxError — Chromium
 * logged a console error and IGNORED the pattern entirely, so
 * checkValidity() returned true for ANY input and the client-side
 * slug hint was dead (server validation stayed authoritative).
 *
 * These tests read the pattern OUT OF THE RENDERED DOM and compile
 * it exactly the way the HTML spec mandates (v flag, implicitly
 * anchored), so a future edit that reintroduces a v-invalid pattern
 * fails here rather than silently dying in the browser.
 */
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ApiProvider } from "../api/ApiProvider";
import { makeClient } from "../api/client";
import { mockFetch } from "../api/mock";
import { CreateNotebookForm } from "./CreateNotebookForm";

function renderForm() {
  return render(
    <ApiProvider client={makeClient(mockFetch, "http://127.0.0.1")}>
      <CreateNotebookForm onCreated={() => undefined} />
    </ApiProvider>,
  );
}

function slugPatternFromDom(): string {
  renderForm();
  const input = screen.getByLabelText<HTMLInputElement>("slug");
  const pattern = input.getAttribute("pattern");
  if (pattern === null) throw new Error("slug input lost its pattern attribute");
  return pattern;
}

describe("CreateNotebookForm slug pattern (v-flag validity)", () => {
  it("compiles under the RegExp v flag (the browser's pattern semantics)", () => {
    const pattern = slugPatternFromDom();
    // Throws SyntaxError if the pattern regresses to a v-invalid
    // form — exactly what Chromium does before ignoring it.
    expect(() => new RegExp(`^(?:${pattern})$`, "v")).not.toThrow();
  });

  it("keeps SLUG_RE semantics: accepts valid slugs, rejects invalid ones", () => {
    const pattern = slugPatternFromDom();
    const re = new RegExp(`^(?:${pattern})$`, "v");
    for (const good of ["abc", "riemann-zeta", "a1-2b", "bridgeland-stability"]) {
      expect(re.test(good), `expected valid: ${good}`).toBe(true);
    }
    for (const bad of ["ab", "Abc", "a_b", "-abc", "1abc", "a".repeat(32)]) {
      expect(re.test(bad), `expected invalid: ${bad}`).toBe(false);
    }
  });
});
