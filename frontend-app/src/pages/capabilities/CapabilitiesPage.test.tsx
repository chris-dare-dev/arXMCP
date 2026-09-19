/**
 * CapabilitiesPage component tests over the CapsProvider seam — zero
 * live server. Covers: the effective-profile list (synthesized default
 * included), the D5 teaching copy (call-time denial, tools/list never
 * filtered — stated on the page AND beside allowlisted rows), the
 * create/edit/delete flows with the exact PUT bodies (token_sha256
 * only), client-side validation, server-422 surfacing, focus
 * discipline, and the honest A1-spine-absent state.
 */
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type {
  CapabilityProfileRow,
  CapsApi,
  ProfileUpsert,
} from "../../api/caps";
import { CapsProvider } from "../../api/CapsProvider";
import { CapabilitiesPage } from "./CapabilitiesPage";

const SYNTH_DEFAULT: CapabilityProfileRow = {
  name: "default",
  enabled: true,
  token_sha256: null,
  tools: null,
  caps: {},
  notebooks: null,
};

const WEBSITE: CapabilityProfileRow = {
  name: "website",
  enabled: true,
  token_sha256: "ab".repeat(32),
  tools: ["search_papers", "get_paper"],
  caps: { search_papers: 5 },
  notebooks: ["bridgeland-stability"],
};

function makeFakeCaps({
  rows = [SYNTH_DEFAULT, WEBSITE],
  unavailable = false,
  putError = null as string | null,
}: {
  rows?: CapabilityProfileRow[];
  unavailable?: boolean;
  putError?: string | null;
} = {}) {
  const store = new Map(rows.map((r) => [r.name, r]));
  const puts: { name: string; body: ProfileUpsert }[] = [];
  const removes: string[] = [];
  const api: CapsApi = {
    async list() {
      if (unavailable) return { kind: "unavailable" };
      return { kind: "ok", items: [...store.values()], total: store.size };
    },
    async upsert(name, body) {
      puts.push({ name, body });
      if (putError !== null) return { kind: "error", detail: putError };
      store.set(name, {
        name,
        enabled: body.enabled,
        token_sha256: body.token_sha256 ?? null,
        tools: body.tools ?? null,
        caps: body.caps ?? {},
        notebooks: body.notebooks ?? null,
      });
      return { kind: "ok" };
    },
    async remove(name) {
      removes.push(name);
      if (!store.has(name)) {
        return { kind: "error", detail: `profile '${name}' not found` };
      }
      store.delete(name);
      return { kind: "ok" };
    },
  };
  return { api, puts, removes, store };
}

function renderPage(api: CapsApi) {
  return render(
    <CapsProvider api={api}>
      <CapabilitiesPage />
    </CapsProvider>,
  );
}

describe("CapabilitiesPage — list + D5 copy", () => {
  it("renders the effective profiles and the D5 teaching block", async () => {
    const { api } = makeFakeCaps();
    renderPage(api);
    await waitFor(() =>
      expect(screen.getByTestId("caps-status").textContent).toBe(
        "2 profiles in force",
      ),
    );
    expect(screen.getByTestId("profile-default")).toBeTruthy();
    expect(screen.getByTestId("profile-website")).toBeTruthy();

    // D5, stated accurately: call-time denial; tools/list never forks.
    const note = screen.getByTestId("d5-note").textContent ?? "";
    expect(note).toContain("tools/list");
    expect(note).toContain("byte-identical");
    expect(note).toContain("call time");
    expect(note).toContain("CAPABILITY_DENIED");
    expect(note).toContain("listed but disabled when called");
    expect(note).not.toContain("hidden");
  });

  it("carries the call-time copy to allowlisted rows (agents see X as disabled)", async () => {
    const { api } = makeFakeCaps();
    renderPage(api);
    const denied = await screen.findByTestId("denied-website");
    // The 6 tools outside the allowlist, named, with the exact model.
    expect(denied.textContent).toContain("lean_verify");
    expect(denied.textContent).toContain("cite_neighbors");
    expect(denied.textContent).toContain("still appear in tools/list");
    expect(denied.textContent).toContain("CAPABILITY_DENIED at call time");
    // Token discipline: only the digest prefix is ever rendered.
    expect(
      screen.getByTestId("profile-website").textContent,
    ).toContain(`token sha256 ${"ab".repeat(6)}`);
  });

  it("states the A1-spine unavailable case honestly", async () => {
    const { api } = makeFakeCaps({ unavailable: true });
    renderPage(api);
    const empty = await screen.findByTestId("caps-unavailable");
    expect(empty.textContent).toContain("/api/v1/capabilities/profiles");
    expect(empty.textContent).toContain("arx-a23");
    expect(empty.textContent).not.toContain("!");
  });
});

describe("CapabilitiesPage — create flow", () => {
  it("creates a profile with the exact PUT body and returns focus", async () => {
    const { api, puts } = makeFakeCaps();
    renderPage(api);
    const newBtn = await screen.findByTestId("new-profile");
    fireEvent.click(newBtn);

    const form = screen.getByTestId("profile-form");
    const name = screen.getByLabelText("Profile name");
    await waitFor(() => expect(document.activeElement).toBe(name));
    fireEvent.change(name, { target: { value: "pipeline" } });
    fireEvent.change(screen.getByLabelText("Token digest (SHA-256)"), {
      target: { value: "C".repeat(64) }, // upper-case: client lowercases
    });
    // Allowlist mode with two tools.
    fireEvent.click(screen.getByLabelText("Allowlist"));
    fireEvent.click(screen.getByLabelText("search_papers"));
    fireEvent.click(screen.getByLabelText("get_chunk"));
    // One cap row.
    fireEvent.click(screen.getByTestId("add-cap-row"));
    fireEvent.change(screen.getByLabelText("Cap 1 tool"), {
      target: { value: "search_papers" },
    });
    fireEvent.change(screen.getByLabelText("Cap 1 max calls"), {
      target: { value: "5" },
    });
    // Notebook allowlist.
    fireEvent.click(screen.getByLabelText("Notebook allowlist"));
    fireEvent.change(
      screen.getByLabelText("Allowed notebook slugs (space or comma separated)"),
      { target: { value: "fourier-duality, bridgeland-stability" } },
    );
    fireEvent.submit(form);

    await waitFor(() => expect(puts).toHaveLength(1));
    expect(puts[0].name).toBe("pipeline");
    expect(puts[0].body).toEqual({
      enabled: true,
      token_sha256: "c".repeat(64),
      tools: ["get_chunk", "search_papers"],
      caps: { search_papers: 5 },
      notebooks: ["bridgeland-stability", "fourier-duality"],
    });
    // Saved: announced, listed, form closed, focus restored.
    await screen.findByTestId("profile-pipeline");
    expect(screen.getByTestId("caps-announce").textContent).toBe(
      "Profile pipeline saved.",
    );
    expect(screen.queryByTestId("profile-form")).toBeNull();
    await waitFor(() =>
      expect(document.activeElement).toBe(screen.getByTestId("new-profile")),
    );
  });

  it("rejects a bad name, a bad token, and a duplicate name inline", async () => {
    const { api, puts } = makeFakeCaps();
    renderPage(api);
    fireEvent.click(await screen.findByTestId("new-profile"));
    const form = screen.getByTestId("profile-form");
    const name = screen.getByLabelText("Profile name");

    fireEvent.change(name, { target: { value: "Bad Name" } });
    fireEvent.submit(form);
    let error = await screen.findByTestId("form-error");
    expect(error.textContent).toContain("lowercase");
    await waitFor(() => expect(document.activeElement).toBe(error));

    fireEvent.change(name, { target: { value: "website" } });
    fireEvent.submit(form);
    error = await screen.findByTestId("form-error");
    expect(error.textContent).toContain("already exists");

    fireEvent.change(name, { target: { value: "fresh" } });
    fireEvent.change(screen.getByLabelText("Token digest (SHA-256)"), {
      target: { value: "not-hex" },
    });
    fireEvent.submit(form);
    error = await screen.findByTestId("form-error");
    expect(error.textContent).toContain("64 hex characters");

    expect(puts).toHaveLength(0);
  });

  it("surfaces a server 422 in the form without closing it", async () => {
    const { api } = makeFakeCaps({ putError: "cap for tool 'x' must be a non-negative integer" });
    renderPage(api);
    fireEvent.click(await screen.findByTestId("new-profile"));
    fireEvent.change(screen.getByLabelText("Profile name"), {
      target: { value: "fresh" },
    });
    fireEvent.submit(screen.getByTestId("profile-form"));
    const error = await screen.findByTestId("form-error");
    expect(error.textContent).toContain("non-negative integer");
    expect(screen.getByTestId("profile-form")).toBeTruthy();
  });
});

describe("CapabilitiesPage — edit + delete", () => {
  it("prefills the edit form and PUTs the full replacement", async () => {
    const { api, puts } = makeFakeCaps();
    renderPage(api);
    fireEvent.click(await screen.findByTestId("edit-website"));

    // Prefilled from the row: allowlist mode, both tools checked.
    const search = screen.getByLabelText("search_papers") as HTMLInputElement;
    expect(search.checked).toBe(true);
    // Flip to disabled and drop a tool: the PUT replaces wholesale.
    fireEvent.click(screen.getByLabelText("Enabled"));
    fireEvent.click(search);
    fireEvent.submit(screen.getByTestId("profile-form"));

    await waitFor(() => expect(puts).toHaveLength(1));
    expect(puts[0].name).toBe("website");
    expect(puts[0].body.enabled).toBe(false);
    expect(puts[0].body.tools).toEqual(["get_paper"]);
    expect(puts[0].body.token_sha256).toBe("ab".repeat(32));
    // Disabled profile renders the call-time teaching line.
    const row = await screen.findByTestId("profile-website");
    await waitFor(() =>
      expect(row.textContent).toContain("agents still see every tool listed"),
    );
  });

  it("switching edit targets resets the form (never saves B under A's name)", async () => {
    const rows = [
      SYNTH_DEFAULT,
      WEBSITE,
      {
        name: "pipeline",
        enabled: true,
        token_sha256: "cd".repeat(32),
        tools: null,
        caps: {},
        notebooks: null,
      },
    ];
    const { api, puts } = makeFakeCaps({ rows });
    renderPage(api);
    fireEvent.click(await screen.findByTestId("edit-website"));
    expect(screen.getByTestId("profile-form").textContent).toContain(
      "Edit profile: website",
    );
    // Switch target WITHOUT closing: the form must remount fresh.
    fireEvent.click(screen.getByTestId("edit-pipeline"));
    expect(screen.getByTestId("profile-form").textContent).toContain(
      "Edit profile: pipeline",
    );
    fireEvent.submit(screen.getByTestId("profile-form"));
    await waitFor(() => expect(puts).toHaveLength(1));
    expect(puts[0].name).toBe("pipeline");
    expect(puts[0].body.token_sha256).toBe("cd".repeat(32));
  });

  it("deletes behind a two-step confirm", async () => {
    const { api, removes } = makeFakeCaps();
    renderPage(api);
    fireEvent.click(await screen.findByTestId("delete-website"));
    // Armed, not fired.
    expect(removes).toHaveLength(0);
    fireEvent.click(screen.getByTestId("confirm-delete-website"));
    await waitFor(() => expect(removes).toEqual(["website"]));
    await waitFor(() =>
      expect(screen.queryByTestId("profile-website")).toBeNull(),
    );
    expect(screen.getByTestId("caps-announce").textContent).toBe(
      "Profile website deleted.",
    );
  });

  it("surfaces the synthesized-default delete failure verbatim", async () => {
    // The fake mirrors the server: a name not operator-defined 404s
    // with a named detail; the synthesized default is exactly that
    // (it lives in no store — defining it is the lockdown path).
    const base = makeFakeCaps({ rows: [SYNTH_DEFAULT] }).api;
    const api: CapsApi = {
      ...base,
      remove: async () => ({
        kind: "error",
        detail: "profile 'default' not found",
      }),
    };
    renderPage(api);
    fireEvent.click(await screen.findByTestId("delete-default"));
    fireEvent.click(screen.getByTestId("confirm-delete-default"));
    await waitFor(() =>
      expect(screen.getByTestId("caps-announce").textContent).toContain(
        "profile 'default' not found",
      ),
    );
  });
});
