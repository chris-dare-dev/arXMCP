/**
 * Inline display-name editor (brief §7.1 notebook detail header).
 * The server strips control characters and returns the STORED value —
 * the UI echoes that, never its own input. The aria-live confirm line
 * stays mounted across mode switches (text updates, never remounts).
 */
import { useState, type FormEvent } from "react";
import { useApi } from "../../api/ApiProvider";
import { errorDetail } from "../../api/errors";
import type { RenameResult } from "../../api/types";

export function RenameControl({
  slug,
  displayName,
  onRenamed,
}: {
  slug: string;
  displayName: string;
  onRenamed: (stored: string) => void;
}) {
  const api = useApi();
  const [editing, setEditing] = useState(false);
  const [value, setValue] = useState(displayName);
  const [busy, setBusy] = useState(false);
  const [line, setLine] = useState("");

  async function save(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    const { data, error, response } = await api.PATCH("/api/v1/notebooks/{slug}", {
      params: { path: { slug } },
      body: { display_name: value },
    });
    setBusy(false);
    if (error !== undefined || data === undefined) {
      setLine(
        errorDetail(error) ??
          `PATCH /api/v1/notebooks/${slug} failed (${response?.status ?? "network"}).`,
      );
      return;
    }
    const stored = (data as unknown as RenameResult).display_name;
    onRenamed(stored);
    setEditing(false);
    setLine("Display name saved.");
  }

  return (
    <div>
      {!editing && (
        <button
          type="button"
          onClick={() => {
            setValue(displayName);
            setLine("");
            setEditing(true);
          }}
        >
          Rename
        </button>
      )}
      {editing && (
        <form className="inline-edit" onSubmit={(e) => void save(e)}>
          <label htmlFor="rename-input" className="microlabel">
            display name
          </label>
          <input
            id="rename-input"
            type="text"
            maxLength={256}
            value={value}
            onChange={(e) => setValue(e.target.value)}
            disabled={busy}
          />
          <button type="submit" disabled={busy}>
            Save
          </button>
          <button
            type="button"
            disabled={busy}
            onClick={() => {
              setEditing(false);
              setLine("");
            }}
          >
            Cancel
          </button>
        </form>
      )}
      <p aria-live="polite" className="reg-telemetry" data-testid="rename-status">
        {line}
      </p>
    </div>
  );
}
