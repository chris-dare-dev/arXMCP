/**
 * Danger zone [C/T] (brief §7.3): destructive ops rule-separated,
 * loudest focus ring on the danger button (base.css), no decorative
 * motion (MOT-NO-8). Delete is metadata-only server-side and the copy
 * says exactly that (CP-1: domain facts, not marketing).
 */
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useApi } from "../../api/ApiProvider";
import { errorDetail } from "../../api/errors";

export function DangerZone({ slug }: { slug: string }) {
  const api = useApi();
  const navigate = useNavigate();
  const [armed, setArmed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [line, setLine] = useState("");

  async function doDelete() {
    setBusy(true);
    setLine("Deleting notebook…");
    const { error, response } = await api.DELETE("/api/v1/notebooks/{slug}", {
      params: { path: { slug } },
    });
    if (error !== undefined) {
      setBusy(false);
      setArmed(false);
      setLine(
        errorDetail(error) ??
          `DELETE /api/v1/notebooks/${slug} failed (${response?.status ?? "network"}).`,
      );
      return;
    }
    void navigate("/");
  }

  return (
    <section aria-labelledby="danger-h">
      <div className="section-header">
        <h3 id="danger-h">Danger zone</h3>
      </div>
      <p className="reg-telemetry note-muted">
        Delete removes the registry row and metadata only — on-disk LanceDB
        data under var/arxmcp/notebooks/{slug}/ is not touched.
      </p>
      {!armed && (
        <button type="button" className="danger" onClick={() => setArmed(true)}>
          Delete notebook…
        </button>
      )}
      {armed && (
        <div className="form-row">
          <button
            type="button"
            className="danger"
            disabled={busy}
            onClick={() => void doDelete()}
          >
            Confirm delete
          </button>
          <button type="button" disabled={busy} onClick={() => setArmed(false)}>
            Cancel
          </button>
        </div>
      )}
      <p aria-live="polite" className="reg-telemetry" data-testid="delete-status">
        {line}
      </p>
    </section>
  );
}
