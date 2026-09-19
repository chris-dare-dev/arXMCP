/**
 * Inline create form on the notebook index (brief §7.1). Chrome
 * register [C]: flush-left labels, hairline borders, radius ≤2px,
 * in-flight disabled state (dim is a signal, not motion). Server
 * validation is authoritative — the client pattern mirrors SLUG_RE
 * (^[a-z][a-z0-9-]{2,30}$) purely as an early hint; 409/422 details
 * are surfaced verbatim in the mounted aria-live line.
 */
import { useState, type FormEvent } from "react";
import { useApi } from "../api/ApiProvider";
import { errorDetail } from "../api/errors";

type CreateState =
  | { phase: "idle" }
  | { phase: "running" }
  | { phase: "done"; slug: string }
  | { phase: "error"; detail: string };

export function CreateNotebookForm({
  onCreated,
}: {
  onCreated: (slug: string) => void;
}) {
  const api = useApi();
  const [slug, setSlug] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [kind, setKind] = useState("arxiv");
  const [state, setState] = useState<CreateState>({ phase: "idle" });

  async function submit(e: FormEvent) {
    e.preventDefault();
    setState({ phase: "running" });
    const { data, error, response } = await api.POST("/api/v1/notebooks", {
      // Full body: the IF-1 dump requires every field (server-side
      // defaults are Pydantic defaults, not schema-optional); empty
      // strings mirror those defaults exactly.
      body: {
        slug,
        display_name: displayName,
        notebook_kind: kind,
        // Integration (a45 x b2): the merged server's NotebookCreate
        // grew a `chunker` field (AC-A.18, default "html"); the form
        // mirrors the server default exactly, like the fields below.
        // A chunker *picker* is a follow-up UI decision, not wired
        // here.
        chunker: "html",
        discovery_category: "",
        description: "",
      },
    });
    if (error !== undefined || data === undefined) {
      setState({
        phase: "error",
        detail:
          errorDetail(error) ??
          `POST /api/v1/notebooks failed (${response?.status ?? "network"}).`,
      });
      return;
    }
    setState({ phase: "done", slug });
    setSlug("");
    setDisplayName("");
    onCreated(slug);
  }

  return (
    <form onSubmit={(e) => void submit(e)} aria-labelledby="create-h">
      <div className="section-header">
        <h3 id="create-h">Create notebook</h3>
      </div>
      <div className="form-row">
        <div className="field">
          <label htmlFor="create-slug">slug</label>
          <input
            id="create-slug"
            type="text"
            required
            // Browsers compile `pattern` with the RegExp v flag, under
            // which an unescaped non-terminal hyphen in a character
            // class is a SyntaxError — the browser then IGNORES the
            // pattern (checkValidity() true for ANY input) and logs a
            // console error. Escaped hyphen keeps the hint alive.
            // (arx-b2 fix pass, verification finding 2.)
            pattern="[a-z][a-z0-9\-]{2,30}"
            maxLength={31}
            value={slug}
            onChange={(e) => setSlug(e.target.value)}
            disabled={state.phase === "running"}
          />
        </div>
        <div className="field">
          <label htmlFor="create-name">display name</label>
          <input
            id="create-name"
            type="text"
            maxLength={256}
            value={displayName}
            onChange={(e) => setDisplayName(e.target.value)}
            disabled={state.phase === "running"}
          />
        </div>
        <div className="field">
          <label htmlFor="create-kind">kind</label>
          <select
            id="create-kind"
            value={kind}
            onChange={(e) => setKind(e.target.value)}
            disabled={state.phase === "running"}
          >
            <option value="arxiv">arxiv</option>
            <option value="textbook">textbook</option>
          </select>
        </div>
        <button type="submit" disabled={state.phase === "running"}>
          Create notebook
        </button>
      </div>
      <p aria-live="polite" className="reg-telemetry" data-testid="create-status">
        {state.phase === "running" && "Creating notebook…"}
        {state.phase === "done" && `Notebook ${state.slug} created.`}
        {state.phase === "error" && state.detail}
      </p>
    </form>
  );
}
