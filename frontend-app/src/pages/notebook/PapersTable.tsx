/**
 * Papers table [T body] (brief §7.1): full-bleed data table, rule +
 * smallcaps headers, no zebra, tabular-nums. Junction rows only at
 * this stage — titles are honestly absent until the papers-metadata
 * table lands (WS-A A4/A5; brief §6.4 dep 3), and the copy says so
 * rather than faking an editorial column. Row action: two-step remove
 * (junction-row delete), announced through one mounted live region.
 */
import { useState } from "react";
import { useApi } from "../../api/ApiProvider";
import { errorDetail } from "../../api/errors";
import type { PaperRow } from "../../api/types";

export function PapersTable({
  slug,
  papers,
  papersError,
  onChanged,
}: {
  slug: string;
  papers: PaperRow[];
  papersError: string | null;
  onChanged: () => void;
}) {
  const api = useApi();
  const [armedId, setArmedId] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [line, setLine] = useState("");

  async function remove(paperId: string) {
    setBusyId(paperId);
    setLine(`Removing ${paperId}…`);
    const { error, response } = await api.DELETE(
      "/api/v1/notebooks/{slug}/papers/{paper_id}",
      { params: { path: { slug, paper_id: paperId } } },
    );
    setBusyId(null);
    setArmedId(null);
    if (error !== undefined) {
      setLine(
        errorDetail(error) ??
          `DELETE /api/v1/notebooks/${slug}/papers/${paperId} failed (${response?.status ?? "network"}).`,
      );
      return;
    }
    setLine(`Removed ${paperId} from the notebook.`);
    onChanged();
  }

  return (
    <section aria-labelledby="papers-h">
      <div className="section-header">
        <h3 id="papers-h">Papers</h3>
      </div>

      <p aria-live="polite" className="reg-telemetry" data-testid="papers-status">
        {papersError ?? `${papers.length} paper${papers.length === 1 ? "" : "s"}`}
      </p>

      {papersError === null && papers.length === 0 && (
        <div className="empty-state">
          <p>No papers in this notebook.</p>
          <p>Add an arXiv paper by URL, or run topic discovery below.</p>
        </div>
      )}

      {papersError === null && papers.length > 0 && (
        <>
          <div className="table-scroll">
            <table className="data" data-testid="papers-table">
              <thead>
                <tr>
                  <th scope="col">arXiv ID</th>
                  <th scope="col">added</th>
                  <th scope="col">stored copy</th>
                  <th scope="col">actions</th>
                </tr>
              </thead>
              <tbody>
                {papers.map((p) => (
                  <tr key={p.paper_id}>
                    <td>
                      <span className="chip">{p.paper_id}</span>
                    </td>
                    <td>{p.added_at}</td>
                    <td>
                      {/* Stored-document math track (D7): the preview
                          route serves the paper's LaTeXML HTML under a
                          zero-JS CSP — MathML Core renders the math
                          natively (spike-verified). The /api/v1 junction
                          row does not expose has_preview (WS-A
                          follow-up), so the link is honest about 404s
                          in its title. */}
                      <a
                        href={`/ui/notebooks/${slug}/papers/${p.paper_id}/preview`}
                        target="_blank"
                        rel="noopener noreferrer"
                        title="Stored HTML rendition (MathML; 404 when no copy is stored)"
                      >
                        view →
                      </a>
                    </td>
                    <td>
                      {armedId !== p.paper_id && (
                        <button
                          type="button"
                          className="danger"
                          disabled={busyId !== null}
                          onClick={() => setArmedId(p.paper_id)}
                        >
                          Remove…
                        </button>
                      )}
                      {armedId === p.paper_id && (
                        <>
                          <button
                            type="button"
                            className="danger"
                            disabled={busyId !== null}
                            onClick={() => void remove(p.paper_id)}
                          >
                            Confirm remove
                          </button>{" "}
                          <button
                            type="button"
                            disabled={busyId !== null}
                            onClick={() => setArmedId(null)}
                          >
                            Cancel
                          </button>
                        </>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="reg-telemetry note-muted">
            Titles render once the papers-metadata table lands (WS-A).
          </p>
        </>
      )}

      <p aria-live="polite" className="reg-telemetry" data-testid="papers-action-status">
        {line}
      </p>
    </section>
  );
}
