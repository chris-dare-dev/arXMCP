/**
 * Vitest setup: RTL's auto-cleanup hooks into afterEach only when test
 * globals are injected; this project keeps globals off (explicit
 * imports), so component roots must be torn down here or queries leak
 * across tests within a file.
 */
import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

afterEach(() => {
  cleanup();
});
