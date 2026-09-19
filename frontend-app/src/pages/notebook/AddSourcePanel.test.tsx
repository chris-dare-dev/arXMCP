/**
 * Unified add-source panel: URL routing against BOTH server
 * generations (the A1 spine that 422s native arxiv.org/html URLs →
 * the documented degrade-to-abs retry; an a45-shaped server that
 * accepts them verbatim), inline validation states, and the XHR
 * upload leg with scripted progress events.
 */
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ApiProvider } from "../../api/ApiProvider";
import { makeClient } from "../../api/client";
import { jsonResponse } from "../../api/mock";
import { AddSourcePanel } from "./AddSourcePanel";

/** Fetch stub for POST /papers: `acceptNativeHtml` flips between the
 * A1-spine behavior (422 on arxiv.org/html) and the a45 behavior. */
function papersServer({ acceptNativeHtml }: { acceptNativeHtml: boolean }) {
  const posted: string[] = [];
  const fetchImpl: typeof fetch = async (input, init) => {
    const req = input instanceof Request ? input : null;
    const url = new URL(
      typeof input === "string" || input instanceof URL
        ? String(input)
        : (req?.url ?? ""),
      "http://127.0.0.1",
    );
    const method = (init?.method ?? req?.method ?? "GET").toUpperCase();
    if (method === "POST" && url.pathname === "/api/v1/notebooks/demo/papers") {
      const text = req !== null ? await req.text() : String(init?.body ?? "{}");
      const arxivUrl = String(
        (JSON.parse(text) as { arxiv_url?: unknown }).arxiv_url ?? "",
      );
      posted.push(arxivUrl);
      const abs = arxivUrl.match(/^https:\/\/arxiv\.org\/abs\/(.+)$/);
      const ar5iv = arxivUrl.match(
        /^https:\/\/ar5iv\.labs\.arxiv\.org\/html\/(.+)$/,
      );
      const native = arxivUrl.match(/^https:\/\/arxiv\.org\/html\/(.+)$/);
      const id =
        abs?.[1] ?? ar5iv?.[1] ?? (acceptNativeHtml ? native?.[1] : undefined);
      if (id === undefined) {
        return jsonResponse(
          {
            detail: `arxiv_url '${arxivUrl}' did not match an accepted form (expected: https://arxiv.org/abs/<paper_id>)`,
          },
          422,
        );
      }
      return jsonResponse(
        { format_version: 1, slug: "demo", paper_id: id },
        201,
      );
    }
    return jsonResponse({ error: "not_mocked", path: url.pathname }, 404);
  };
  return { fetchImpl, posted };
}

function renderPanel(
  fetchImpl: typeof fetch,
  props: Partial<Parameters<typeof AddSourcePanel>[0]> = {},
) {
  const onAdded = props.onAdded ?? (() => {});
  return render(
    <ApiProvider client={makeClient(fetchImpl, "http://127.0.0.1")}>
      <AddSourcePanel
        slug="demo"
        notebookKind="arxiv"
        onAdded={onAdded}
        {...props}
      />
    </ApiProvider>,
  );
}

describe("URL leg", () => {
  it("posts an abs URL and reports success", async () => {
    const { fetchImpl, posted } = papersServer({ acceptNativeHtml: false });
    let added = 0;
    renderPanel(fetchImpl, { onAdded: () => (added += 1) });

    fireEvent.change(screen.getByLabelText("arXiv URL or paper id"), {
      target: { value: "https://arxiv.org/abs/2401.00001" },
    });
    expect(screen.getByTestId("source-hint").textContent).toBe(
      "arXiv abstract page → paper 2401.00001",
    );
    fireEvent.click(screen.getByRole("button", { name: "Add paper" }));
    await waitFor(() =>
      expect(screen.getByTestId("addsource-status").textContent).toBe(
        "Added 2401.00001.",
      ),
    );
    expect(posted).toEqual(["https://arxiv.org/abs/2401.00001"]);
    expect(added).toBe(1);
  });

  it("degrades a native-HTML URL to the abs form on the A1 spine", async () => {
    const { fetchImpl, posted } = papersServer({ acceptNativeHtml: false });
    renderPanel(fetchImpl);

    fireEvent.change(screen.getByLabelText("arXiv URL or paper id"), {
      target: { value: "https://arxiv.org/html/2403.33333" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Add paper" }));
    await waitFor(() =>
      expect(screen.getByTestId("addsource-status").textContent).toContain(
        "Added 2403.33333.",
      ),
    );
    expect(screen.getByTestId("addsource-status").textContent).toContain(
      "does not accept arxiv.org/html URLs yet",
    );
    expect(posted).toEqual([
      "https://arxiv.org/html/2403.33333",
      "https://arxiv.org/abs/2403.33333",
    ]);
  });

  it("posts a native-HTML URL verbatim once, on an a45-shaped server", async () => {
    const { fetchImpl, posted } = papersServer({ acceptNativeHtml: true });
    renderPanel(fetchImpl);

    fireEvent.change(screen.getByLabelText("arXiv URL or paper id"), {
      target: { value: "https://arxiv.org/html/2403.33333" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Add paper" }));
    await waitFor(() =>
      expect(screen.getByTestId("addsource-status").textContent).toBe(
        "Added 2403.33333.",
      ),
    );
    expect(posted).toEqual(["https://arxiv.org/html/2403.33333"]);
  });

  it("routes ar5iv URLs verbatim and bare ids via the abs form", async () => {
    const { fetchImpl, posted } = papersServer({ acceptNativeHtml: false });
    renderPanel(fetchImpl);

    fireEvent.change(screen.getByLabelText("arXiv URL or paper id"), {
      target: { value: "https://ar5iv.labs.arxiv.org/html/2402.22222" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Add paper" }));
    await waitFor(() =>
      expect(screen.getByTestId("addsource-status").textContent).toBe(
        "Added 2402.22222.",
      ),
    );

    fireEvent.change(screen.getByLabelText("arXiv URL or paper id"), {
      target: { value: "0705.3794" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Add paper" }));
    await waitFor(() =>
      expect(screen.getByTestId("addsource-status").textContent).toBe(
        "Added 0705.3794.",
      ),
    );
    expect(posted).toEqual([
      "https://ar5iv.labs.arxiv.org/html/2402.22222",
      "https://arxiv.org/abs/0705.3794",
    ]);
  });

  it("shows the inline invalid state without any network call", async () => {
    const { fetchImpl, posted } = papersServer({ acceptNativeHtml: false });
    renderPanel(fetchImpl);

    fireEvent.change(screen.getByLabelText("arXiv URL or paper id"), {
      target: { value: "https://example.com/abs/1" },
    });
    expect(screen.getByTestId("source-hint").textContent).toContain(
      "not an accepted arXiv source",
    );
    fireEvent.click(screen.getByRole("button", { name: "Add paper" }));
    await waitFor(() =>
      expect(screen.getByTestId("addsource-status").textContent).toContain(
        "not an accepted arXiv source",
      ),
    );
    expect(posted).toEqual([]);
  });
});

/** Scriptable XHR double for the upload leg. */
class FakeXhr {
  method = "";
  url = "";
  sent: FormData | null = null;
  status = 0;
  responseText = "";
  private listeners: Record<string, ((ev: unknown) => void)[]> = {};
  private uploadListeners: Record<string, ((ev: unknown) => void)[]> = {};
  upload = {
    addEventListener: (type: string, l: (ev: unknown) => void) => {
      (this.uploadListeners[type] ??= []).push(l);
    },
  };

  addEventListener(type: string, l: (ev: unknown) => void) {
    (this.listeners[type] ??= []).push(l);
  }

  open(method: string, url: string) {
    this.method = method;
    this.url = url;
  }

  send(body: FormData) {
    this.sent = body;
  }

  emitProgress(loaded: number, total: number) {
    for (const l of this.uploadListeners.progress ?? []) {
      l({ lengthComputable: true, loaded, total });
    }
  }

  respond(status: number, body: unknown) {
    this.status = status;
    this.responseText = JSON.stringify(body);
    for (const l of this.listeners.load ?? []) l({});
  }
}

function pickFile(name: string, contents = "<!DOCTYPE html><html></html>") {
  const input = screen.getByLabelText(/HTML file/) as HTMLInputElement;
  const file = new File([contents], name, { type: "text/html" });
  fireEvent.change(input, { target: { files: [file] } });
}

describe("upload leg (XHR)", () => {
  it("uploads with progress and reports created", async () => {
    const { fetchImpl } = papersServer({ acceptNativeHtml: false });
    const xhr = new FakeXhr();
    let added = 0;
    renderPanel(fetchImpl, {
      onAdded: () => (added += 1),
      xhrFactory: () => xhr as unknown as XMLHttpRequest,
    });

    pickFile("0705.3794.html");
    // Filename stem is a valid id → prefilled.
    expect(
      (screen.getByLabelText("paper id", { exact: true }) as HTMLInputElement)
        .value,
    ).toBe("0705.3794");
    fireEvent.click(screen.getByRole("button", { name: "Upload" }));

    await waitFor(() => expect(xhr.sent).not.toBeNull());
    expect(xhr.method).toBe("POST");
    expect(xhr.url).toBe("/api/v1/notebooks/demo/papers/upload");
    expect(xhr.sent?.get("paper_id")).toBe("0705.3794");

    xhr.emitProgress(50, 100);
    await waitFor(() =>
      expect(
        screen.getByTestId("upload-progress").getAttribute("aria-valuenow"),
      ).toBe("50"),
    );

    xhr.respond(201, {
      format_version: 1,
      slug: "demo",
      paper_id: "0705.3794",
      result: "created",
    });
    await waitFor(() =>
      expect(screen.getByTestId("addsource-status").textContent).toBe(
        "Uploaded 0705.3794 (created).",
      ),
    );
    expect(added).toBe(1);
  });

  it("surfaces the server's 413 detail verbatim", async () => {
    const { fetchImpl } = papersServer({ acceptNativeHtml: false });
    const xhr = new FakeXhr();
    renderPanel(fetchImpl, {
      xhrFactory: () => xhr as unknown as XMLHttpRequest,
    });

    pickFile("2401.00001.html");
    fireEvent.click(screen.getByRole("button", { name: "Upload" }));
    await waitFor(() => expect(xhr.sent).not.toBeNull());
    xhr.respond(413, {
      detail: "upload of 11000000 bytes exceeds the 10485760-byte cap",
    });
    await waitFor(() =>
      expect(screen.getByTestId("addsource-status").textContent).toContain(
        "exceeds the 10485760-byte cap",
      ),
    );
  });

  it("rejects a bad paper id client-side (no XHR)", async () => {
    const { fetchImpl } = papersServer({ acceptNativeHtml: false });
    const xhr = new FakeXhr();
    renderPanel(fetchImpl, {
      xhrFactory: () => xhr as unknown as XMLHttpRequest,
    });

    pickFile("notes.html");
    fireEvent.change(screen.getByLabelText("paper id", { exact: true }), {
      target: { value: "not-an-id" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Upload" }));
    await waitFor(() =>
      expect(screen.getByTestId("addsource-status").textContent).toContain(
        "not a valid arXiv id",
      ),
    );
    expect(xhr.sent).toBeNull();
  });

  it("accepts textbook:<slug> ids for textbook-kind notebooks", async () => {
    const { fetchImpl } = papersServer({ acceptNativeHtml: false });
    const xhr = new FakeXhr();
    renderPanel(fetchImpl, {
      notebookKind: "textbook",
      xhrFactory: () => xhr as unknown as XMLHttpRequest,
    });

    const input = screen.getByLabelText(/PDF file/) as HTMLInputElement;
    const file = new File(["%PDF-1.7 fake"], "shimura.pdf", {
      type: "application/pdf",
    });
    fireEvent.change(input, { target: { files: [file] } });
    fireEvent.change(screen.getByLabelText("paper id", { exact: true }), {
      target: { value: "textbook:shimura-varieties" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Upload" }));
    await waitFor(() => expect(xhr.sent).not.toBeNull());
    xhr.respond(201, { result: "created" });
    await waitFor(() =>
      expect(screen.getByTestId("addsource-status").textContent).toBe(
        "Uploaded textbook:shimura-varieties (created).",
      ),
    );
  });
});
