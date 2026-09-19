/**
 * Capability configuration [T] (arx-b3, WS-B over WS-A A2): the
 * operator surface for capability profiles — list the policy actually
 * in force (the synthesized `default` included), create/replace/
 * delete profiles, with the D5 teaching block front and center:
 * profiles gate CALLS, never the tool listing. `tools/list` stays
 * byte-identical for every caller (the BP1 prompt-cache contract);
 * a denied tool is still listed and fails at call time with a
 * structured CAPABILITY_DENIED envelope — to the agent it looks
 * enabled in the listing but behaves as disabled when called.
 *
 * Token discipline (AC-A.10): the form accepts a SHA-256 digest only,
 * with the local hashing recipe beside the field; a token value never
 * crosses even the loopback HTTP surface.
 *
 * Every state is honest: loading / ok / A1-spine-absent (this
 * branch's own server build does not carry the a23 router) / error.
 */
import {
  useCallback,
  useEffect,
  useId,
  useRef,
  useState,
  type FormEvent,
} from "react";
import {
  PROFILE_NAME_RE,
  TOKEN_SHA256_RE,
  type CapabilityProfileRow,
  type ProfileUpsert,
} from "../../api/caps";
import { useCapsApi } from "../../api/CapsProvider";

/** The frozen 8-tool MCP surface on this spine (server/tools.py
 * ALL_TOOLS, TOOL_SCHEMA_VERSION 17). Rendered as allowlist choices;
 * unknown tools already present on a profile are merged in so an
 * integration-era profile round-trips unharmed. */
export const KNOWN_TOOLS = [
  "search_papers",
  "get_chunk",
  "find_equation",
  "get_definitions",
  "find_lemma_by_name",
  "get_paper",
  "cite_neighbors",
  "lean_verify",
] as const;

const HASH_RECIPE =
  "python -c \"import hashlib,getpass;print(hashlib.sha256(getpass.getpass('token: ').encode()).hexdigest())\"";

type ListState =
  | { phase: "loading" }
  | { phase: "ok"; rows: CapabilityProfileRow[] }
  | { phase: "unavailable" }
  | { phase: "error"; detail: string };

type Editing =
  | null
  | { mode: "create" }
  | { mode: "edit"; row: CapabilityProfileRow };

// ---------------------------------------------------------------------------
// Profile form (create + edit share it; PUT is a full replace)
// ---------------------------------------------------------------------------

interface FormValues {
  name: string;
  enabled: boolean;
  token: string;
  toolsMode: "all" | "allowlist";
  toolsSelected: string[];
  capsRows: { tool: string; value: string }[];
  notebooksMode: "unscoped" | "allowlist";
  notebooksText: string;
}

function valuesFromRow(row: CapabilityProfileRow): FormValues {
  return {
    name: row.name,
    enabled: row.enabled,
    token: row.token_sha256 ?? "",
    toolsMode: row.tools === null ? "all" : "allowlist",
    toolsSelected: row.tools ?? [],
    capsRows: Object.entries(row.caps).map(([tool, v]) => ({
      tool,
      value: String(v),
    })),
    notebooksMode: row.notebooks === null ? "unscoped" : "allowlist",
    notebooksText: (row.notebooks ?? []).join(" "),
  };
}

const EMPTY_VALUES: FormValues = {
  name: "",
  enabled: true,
  token: "",
  toolsMode: "all",
  toolsSelected: [],
  capsRows: [],
  notebooksMode: "unscoped",
  notebooksText: "",
};

/** Validate + assemble the PUT body. Returns either a body or a field
 * error message; the server stays the authority (422s surface too). */
function buildBody(
  v: FormValues,
  mode: "create" | "edit",
  existingNames: string[],
): { body: ProfileUpsert; name: string } | { error: string } {
  const name = v.name.trim();
  if (!PROFILE_NAME_RE.test(name)) {
    return {
      error:
        "Profile name must be lowercase alphanumeric plus hyphens, start with a letter, and stay within 64 characters.",
    };
  }
  if (mode === "create" && existingNames.includes(name)) {
    return {
      error: `A profile named ${name} already exists — edit it instead (saving would silently replace it).`,
    };
  }
  const token = v.token.trim().toLowerCase();
  if (token !== "" && !TOKEN_SHA256_RE.test(token)) {
    return {
      error:
        "Token digest must be 64 hex characters (a SHA-256 of the token) — never the token value itself.",
    };
  }
  const caps: Record<string, number> = {};
  for (const row of v.capsRows) {
    const tool = row.tool.trim();
    const value = row.value.trim();
    if (tool === "" && value === "") continue;
    if (tool === "") return { error: "Every cap row needs a tool name." };
    if (tool in caps) return { error: `Duplicate cap for tool ${tool}.` };
    if (!/^\d+$/.test(value)) {
      return { error: `Cap for ${tool} must be a non-negative integer.` };
    }
    caps[tool] = Number(value);
  }
  const body: ProfileUpsert = { enabled: v.enabled };
  if (token !== "") body.token_sha256 = token;
  if (v.toolsMode === "allowlist") body.tools = [...v.toolsSelected].sort();
  if (Object.keys(caps).length > 0) body.caps = caps;
  if (v.notebooksMode === "allowlist") {
    const slugs = v.notebooksText.split(/[\s,]+/).filter((s) => s !== "");
    body.notebooks = [...new Set(slugs)].sort();
  }
  return { body, name };
}

function ProfileForm({
  editing,
  existingNames,
  saving,
  serverError,
  onSave,
  onCancel,
}: {
  editing: Exclude<Editing, null>;
  existingNames: string[];
  saving: boolean;
  serverError: string | null;
  onSave: (name: string, body: ProfileUpsert) => void;
  onCancel: () => void;
}) {
  const mode = editing.mode;
  const [values, setValues] = useState<FormValues>(
    mode === "edit" ? valuesFromRow(editing.row) : EMPTY_VALUES,
  );
  const [fieldError, setFieldError] = useState<string | null>(null);
  const nameRef = useRef<HTMLInputElement>(null);
  const enabledRef = useRef<HTMLInputElement>(null);
  const errorRef = useRef<HTMLParagraphElement>(null);
  const formId = useId();

  // Focus management: opening the form moves focus to its first
  // interactive field; a validation/server error moves it to the
  // error text (role=alert) so keyboard+SR users land on the problem.
  useEffect(() => {
    (mode === "create" ? nameRef : enabledRef).current?.focus();
  }, [mode]);
  const shownError = fieldError ?? serverError;
  useEffect(() => {
    if (shownError !== null) errorRef.current?.focus();
  }, [shownError]);

  const toolChoices = [
    ...KNOWN_TOOLS,
    ...values.toolsSelected.filter(
      (t) => !(KNOWN_TOOLS as readonly string[]).includes(t),
    ),
  ];

  const submit = (e: FormEvent) => {
    e.preventDefault();
    const built = buildBody(values, mode, existingNames);
    if ("error" in built) {
      setFieldError(built.error);
      return;
    }
    setFieldError(null);
    onSave(built.name, built.body);
  };

  return (
    <form
      className="caps-form"
      data-testid="profile-form"
      aria-label={
        mode === "create" ? "New capability profile" : `Edit profile ${values.name}`
      }
      onSubmit={submit}
    >
      <h3 className="section-header">
        {mode === "create" ? "New profile" : `Edit profile: ${values.name}`}
      </h3>

      {shownError !== null && (
        <p
          role="alert"
          tabIndex={-1}
          ref={errorRef}
          className="malformed-note caps-form-error"
          data-testid="form-error"
        >
          {shownError}
        </p>
      )}

      {mode === "create" && (
        <div className="caps-field">
          <label htmlFor={`${formId}-name`}>Profile name</label>
          <input
            id={`${formId}-name`}
            ref={nameRef}
            className="reg-telemetry"
            value={values.name}
            onChange={(e) => setValues((v) => ({ ...v, name: e.target.value }))}
            aria-describedby={`${formId}-name-hint`}
          />
          <p id={`${formId}-name-hint`} className="note-muted">
            Lowercase alphanumeric plus hyphens (the notebook-slug shape).
            Defining <code className="reg-telemetry">default</code> replaces
            the synthesized token-less profile — that is how unauthenticated
            loopback access gets locked down.
          </p>
        </div>
      )}

      <div className="caps-field caps-field-inline">
        <input
          id={`${formId}-enabled`}
          ref={enabledRef}
          type="checkbox"
          checked={values.enabled}
          onChange={(e) =>
            setValues((v) => ({ ...v, enabled: e.target.checked }))
          }
        />
        <label htmlFor={`${formId}-enabled`}>Enabled</label>
        <span className="note-muted">
          A disabled profile denies every call under its token at call time;
          the tool listing is unchanged.
        </span>
      </div>

      <div className="caps-field">
        <label htmlFor={`${formId}-token`}>Token digest (SHA-256)</label>
        <input
          id={`${formId}-token`}
          className="reg-telemetry"
          value={values.token}
          onChange={(e) => setValues((v) => ({ ...v, token: e.target.value }))}
          placeholder="64 hex chars — empty for the token-less profile"
          aria-describedby={`${formId}-token-hint`}
        />
        <p id={`${formId}-token-hint`} className="note-muted">
          Hash locally so the token value never crosses HTTP:{" "}
          <code className="reg-telemetry">{HASH_RECIPE}</code>
        </p>
      </div>

      <fieldset className="caps-field">
        <legend>Tool access</legend>
        <div className="caps-field-inline">
          <input
            id={`${formId}-tools-all`}
            type="radio"
            name={`${formId}-toolsmode`}
            checked={values.toolsMode === "all"}
            onChange={() => setValues((v) => ({ ...v, toolsMode: "all" }))}
          />
          <label htmlFor={`${formId}-tools-all`}>All tools</label>
          <input
            id={`${formId}-tools-allowlist`}
            type="radio"
            name={`${formId}-toolsmode`}
            checked={values.toolsMode === "allowlist"}
            onChange={() =>
              setValues((v) => ({ ...v, toolsMode: "allowlist" }))
            }
          />
          <label htmlFor={`${formId}-tools-allowlist`}>Allowlist</label>
        </div>
        {values.toolsMode === "allowlist" && (
          <>
            <div className="caps-tool-grid" data-testid="tools-allowlist">
              {toolChoices.map((tool) => (
                <span key={tool} className="caps-field-inline">
                  <input
                    id={`${formId}-tool-${tool}`}
                    type="checkbox"
                    checked={values.toolsSelected.includes(tool)}
                    onChange={(e) =>
                      setValues((v) => ({
                        ...v,
                        toolsSelected: e.target.checked
                          ? [...v.toolsSelected, tool]
                          : v.toolsSelected.filter((t) => t !== tool),
                      }))
                    }
                  />
                  <label
                    htmlFor={`${formId}-tool-${tool}`}
                    className="reg-telemetry"
                  >
                    {tool}
                  </label>
                </span>
              ))}
            </div>
            <p className="note-muted">
              Tools left unchecked stay visible in{" "}
              <code className="reg-telemetry">tools/list</code> but answer{" "}
              <code className="reg-telemetry">CAPABILITY_DENIED</code> at call
              time. An empty allowlist denies every tool.
            </p>
          </>
        )}
      </fieldset>

      <fieldset className="caps-field">
        <legend>Per-session call caps</legend>
        <p className="note-muted">
          Overrides the built-in retrieval caps (3 search / 4 chunk) per tool
          for sessions under this profile.
        </p>
        {values.capsRows.map((row, i) => (
          <div className="caps-field-inline" key={i}>
            <label className="visually-hidden" htmlFor={`${formId}-cap-tool-${i}`}>
              Cap {i + 1} tool
            </label>
            <input
              id={`${formId}-cap-tool-${i}`}
              className="reg-telemetry"
              list={`${formId}-tool-names`}
              value={row.tool}
              placeholder="tool"
              onChange={(e) =>
                setValues((v) => ({
                  ...v,
                  capsRows: v.capsRows.map((r, j) =>
                    j === i ? { ...r, tool: e.target.value } : r,
                  ),
                }))
              }
            />
            <label
              className="visually-hidden"
              htmlFor={`${formId}-cap-value-${i}`}
            >
              Cap {i + 1} max calls
            </label>
            <input
              id={`${formId}-cap-value-${i}`}
              className="reg-telemetry caps-cap-value"
              inputMode="numeric"
              value={row.value}
              placeholder="max calls"
              onChange={(e) =>
                setValues((v) => ({
                  ...v,
                  capsRows: v.capsRows.map((r, j) =>
                    j === i ? { ...r, value: e.target.value } : r,
                  ),
                }))
              }
            />
            <button
              type="button"
              onClick={() =>
                setValues((v) => ({
                  ...v,
                  capsRows: v.capsRows.filter((_, j) => j !== i),
                }))
              }
            >
              Remove cap
            </button>
          </div>
        ))}
        <datalist id={`${formId}-tool-names`}>
          {KNOWN_TOOLS.map((t) => (
            <option key={t} value={t} />
          ))}
        </datalist>
        <button
          type="button"
          data-testid="add-cap-row"
          onClick={() =>
            setValues((v) => ({
              ...v,
              capsRows: [...v.capsRows, { tool: "", value: "" }],
            }))
          }
        >
          Add cap
        </button>
      </fieldset>

      <fieldset className="caps-field">
        <legend>Notebook scope</legend>
        <div className="caps-field-inline">
          <input
            id={`${formId}-nb-unscoped`}
            type="radio"
            name={`${formId}-nbmode`}
            checked={values.notebooksMode === "unscoped"}
            onChange={() =>
              setValues((v) => ({ ...v, notebooksMode: "unscoped" }))
            }
          />
          <label htmlFor={`${formId}-nb-unscoped`}>Unscoped</label>
          <input
            id={`${formId}-nb-allowlist`}
            type="radio"
            name={`${formId}-nbmode`}
            checked={values.notebooksMode === "allowlist"}
            onChange={() =>
              setValues((v) => ({ ...v, notebooksMode: "allowlist" }))
            }
          />
          <label htmlFor={`${formId}-nb-allowlist`}>Notebook allowlist</label>
        </div>
        {values.notebooksMode === "allowlist" && (
          <div className="caps-field">
            <label htmlFor={`${formId}-notebooks`}>
              Allowed notebook slugs (space or comma separated)
            </label>
            <input
              id={`${formId}-notebooks`}
              className="reg-telemetry"
              value={values.notebooksText}
              onChange={(e) =>
                setValues((v) => ({ ...v, notebooksText: e.target.value }))
              }
            />
            <p className="note-muted">
              A scoped profile is also denied UNSCOPED searches — otherwise
              the scope would leak the shared corpus.
            </p>
          </div>
        )}
      </fieldset>

      <div className="caps-form-actions">
        <button type="submit" data-testid="save-profile" disabled={saving}>
          {saving ? "Saving…" : "Save profile"}
        </button>
        <button type="button" onClick={onCancel} disabled={saving}>
          Cancel
        </button>
      </div>
    </form>
  );
}

// ---------------------------------------------------------------------------
// Profile row (read view)
// ---------------------------------------------------------------------------

function ProfileRow({
  row,
  confirming,
  busy,
  onEdit,
  onDeleteArm,
  onDeleteConfirm,
  onDeleteCancel,
}: {
  row: CapabilityProfileRow;
  confirming: boolean;
  busy: boolean;
  onEdit: () => void;
  onDeleteArm: () => void;
  onDeleteConfirm: () => void;
  onDeleteCancel: () => void;
}) {
  const denied =
    row.tools === null
      ? []
      : (KNOWN_TOOLS as readonly string[]).filter(
          (t) => !row.tools?.includes(t),
        );
  return (
    <li className="caps-row" data-testid={`profile-${row.name}`}>
      <div className="caps-row-head">
        <span className="chip">{row.name}</span>
        <span className={row.enabled ? "badge badge-ok" : "badge badge-down"}>
          {row.enabled ? "enabled" : "disabled"}
        </span>
        <span className="reg-telemetry note-muted">
          {row.token_sha256 === null
            ? "token-less (unauthenticated loopback)"
            : `token sha256 ${row.token_sha256.slice(0, 12)}…`}
        </span>
        <span className="caps-row-actions">
          <button type="button" data-testid={`edit-${row.name}`} onClick={onEdit}>
            Edit
          </button>
          {!confirming ? (
            <button
              type="button"
              data-testid={`delete-${row.name}`}
              onClick={onDeleteArm}
            >
              Delete
            </button>
          ) : (
            <>
              <button
                type="button"
                className="danger"
                data-testid={`confirm-delete-${row.name}`}
                onClick={onDeleteConfirm}
                disabled={busy}
              >
                Confirm delete
              </button>
              <button type="button" onClick={onDeleteCancel} disabled={busy}>
                Cancel
              </button>
            </>
          )}
        </span>
      </div>
      <dl className="caps-row-body reg-telemetry">
        <div>
          <dt className="microlabel">tools</dt>
          <dd data-testid={`tools-${row.name}`}>
            {row.tools === null ? (
              "all tools"
            ) : row.tools.length === 0 ? (
              "none (deny-all)"
            ) : (
              <>
                {row.tools.map((t) => (
                  <span key={t} className="chip">
                    {t}
                  </span>
                ))}
              </>
            )}
            {!row.enabled && (
              <span className="note-muted">
                {" "}
                — profile disabled: agents still see every tool listed; each
                call answers CAPABILITY_DENIED.
              </span>
            )}
            {row.enabled && denied.length > 0 && (
              <span className="note-muted" data-testid={`denied-${row.name}`}>
                {" "}
                — {denied.join(", ")} still appear in tools/list but answer
                CAPABILITY_DENIED at call time.
              </span>
            )}
          </dd>
        </div>
        <div>
          <dt className="microlabel">session caps</dt>
          <dd>
            {Object.keys(row.caps).length === 0
              ? "built-in defaults (3 search / 4 chunk)"
              : Object.entries(row.caps)
                  .map(([t, n]) => `${t} ≤ ${n}`)
                  .join(" · ")}
          </dd>
        </div>
        <div>
          <dt className="microlabel">notebooks</dt>
          <dd>
            {row.notebooks === null
              ? "unscoped"
              : row.notebooks.length === 0
                ? "none"
                : row.notebooks.join(", ")}
          </dd>
        </div>
      </dl>
    </li>
  );
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export function CapabilitiesPage() {
  const caps = useCapsApi();
  const [list, setList] = useState<ListState>({ phase: "loading" });
  const [editing, setEditing] = useState<Editing>(null);
  const [saving, setSaving] = useState(false);
  const [serverError, setServerError] = useState<string | null>(null);
  const [confirming, setConfirming] = useState<string | null>(null);
  const [announce, setAnnounce] = useState("");
  const [reloadKey, setReloadKey] = useState(0);
  /** data-testid of the control to restore focus to when the form
   * closes (the invoker — dialog-pattern focus discipline). */
  const returnFocusTo = useRef<string | null>(null);
  const rootRef = useRef<HTMLElement>(null);

  useEffect(() => {
    let cancelled = false;
    void caps.list().then((result) => {
      if (cancelled) return;
      if (result.kind === "ok") setList({ phase: "ok", rows: result.items });
      else if (result.kind === "unavailable") setList({ phase: "unavailable" });
      else setList({ phase: "error", detail: result.detail });
    });
    return () => {
      cancelled = true;
    };
  }, [caps, reloadKey]);

  const restoreFocus = useCallback(() => {
    const id = returnFocusTo.current;
    returnFocusTo.current = null;
    if (id === null) return;
    // The row may have been deleted; fall back to the page heading's
    // sibling control so keyboard users never lose their place.
    const el =
      rootRef.current?.querySelector<HTMLElement>(`[data-testid="${id}"]`) ??
      rootRef.current?.querySelector<HTMLElement>('[data-testid="new-profile"]');
    el?.focus();
  }, []);

  const closeForm = useCallback(() => {
    setEditing(null);
    setServerError(null);
    // Restore after the re-render removes the form.
    setTimeout(restoreFocus, 0);
  }, [restoreFocus]);

  const onSave = useCallback(
    (name: string, body: ProfileUpsert) => {
      setSaving(true);
      setServerError(null);
      void caps.upsert(name, body).then((result) => {
        setSaving(false);
        if (result.kind === "ok") {
          setAnnounce(`Profile ${name} saved.`);
          setReloadKey((k) => k + 1);
          closeForm();
        } else if (result.kind === "unavailable") {
          setServerError(
            "The capabilities API vanished mid-edit (server build without the arx-a23 router).",
          );
        } else {
          setServerError(result.detail);
        }
      });
    },
    [caps, closeForm],
  );

  const onDelete = useCallback(
    (name: string) => {
      setSaving(true);
      void caps.remove(name).then((result) => {
        setSaving(false);
        setConfirming(null);
        if (result.kind === "ok") {
          setAnnounce(`Profile ${name} deleted.`);
        } else if (result.kind === "unavailable") {
          setAnnounce(
            "Delete failed: the capabilities API is absent on this server build.",
          );
        } else {
          // Deleting a synthesized default 404s with a named detail —
          // surfaced verbatim (it is not operator-defined, so there is
          // nothing to delete; defining it is the lockdown path).
          setAnnounce(`Delete failed: ${result.detail}`);
        }
        setReloadKey((k) => k + 1);
        setTimeout(restoreFocus, 0);
      });
    },
    [caps, restoreFocus],
  );

  const rows = list.phase === "ok" ? list.rows : [];

  return (
    <section aria-labelledby="caps-h" className="obs-page" ref={rootRef}>
      <div className="section-header">
        <h2 id="caps-h">Capabilities</h2>
      </div>

      {/* D5 — the teaching block. Enforcement model stated exactly:
          call-time denial, never tools/list filtering. */}
      <div className="caps-explainer" data-testid="d5-note">
        <p>
          Profiles gate <strong>calls</strong>, never the tool listing.{" "}
          <code className="reg-telemetry">tools/list</code> is byte-identical
          for every caller — the full {KNOWN_TOOLS.length}-tool surface —
          because per-profile filtering would fork the listing and break the
          BP1 prompt-cache contract.
        </p>
        <p>
          Enforcement happens at call time: a call outside a profile&rsquo;s
          allowlist (or under a disabled profile, or outside its notebook
          scope) returns a structured{" "}
          <code className="reg-telemetry">CAPABILITY_DENIED</code> error
          envelope. An agent therefore sees a denied tool as{" "}
          <em>listed but disabled when called</em> — it never disappears from
          the tool surface.
        </p>
      </div>

      <p aria-live="polite" className="reg-telemetry" data-testid="caps-status">
        {list.phase === "loading" && "Loading profiles…"}
        {list.phase === "ok" &&
          `${rows.length} profile${rows.length === 1 ? "" : "s"} in force`}
        {list.phase === "unavailable" && "Capabilities API unavailable."}
        {list.phase === "error" && list.detail}
      </p>
      <p aria-live="polite" className="reg-telemetry" data-testid="caps-announce">
        {announce}
      </p>

      {list.phase === "unavailable" && (
        <div className="empty-state" data-testid="caps-unavailable">
          <p>
            This server build does not expose{" "}
            <code className="reg-telemetry">
              /api/v1/capabilities/profiles
            </code>
            .
          </p>
          <p>
            Capability profiles ship with the arx-a23 server slice — run a
            build that includes it, then reload this page. Until then the
            server behaves as the synthesized permissive default (day-one
            behavior, all tools, built-in caps).
          </p>
        </div>
      )}

      {list.phase === "ok" && (
        <>
          <div className="caps-toolbar">
            <button
              type="button"
              data-testid="new-profile"
              onClick={() => {
                returnFocusTo.current = "new-profile";
                setServerError(null);
                setEditing({ mode: "create" });
              }}
              disabled={editing !== null}
            >
              New profile
            </button>
          </div>

          {editing !== null && (
            <ProfileForm
              // Remount on target change: switching Edit A -> Edit B
              // must reset the form state, or B would be edited with
              // A's values and SAVED UNDER A's NAME (full-replace PUT).
              key={editing.mode === "edit" ? `edit-${editing.row.name}` : "create"}
              editing={editing}
              existingNames={rows.map((r) => r.name)}
              saving={saving}
              serverError={serverError}
              onSave={onSave}
              onCancel={closeForm}
            />
          )}

          <ul className="caps-list" data-testid="caps-list">
            {rows.map((row) => (
              <ProfileRow
                key={row.name}
                row={row}
                confirming={confirming === row.name}
                busy={saving}
                onEdit={() => {
                  returnFocusTo.current = `edit-${row.name}`;
                  setServerError(null);
                  setEditing({ mode: "edit", row });
                }}
                onDeleteArm={() => setConfirming(row.name)}
                onDeleteConfirm={() => {
                  returnFocusTo.current = "new-profile";
                  onDelete(row.name);
                }}
                onDeleteCancel={() => setConfirming(null)}
              />
            ))}
          </ul>
        </>
      )}
    </section>
  );
}
