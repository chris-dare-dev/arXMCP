/**
 * Discovery panel (brief §7.1): propose→confirm flow. POST /discover
 * returns an EPHEMERAL candidate queue (nothing persists server-side);
 * each candidate is confirmed individually by POSTing its abs URL to
 * /papers. Candidate prose is editorial register; controls and IDs are
 * telemetry. One mounted aria-live region carries run + add outcomes
 * (NO-14: one live region at a time on this panel).
 */
import { useCallback, useState } from "react";
import { useApi } from "../../api/ApiProvider";
import { errorDetail } from "../../api/errors";
import type { DiscoverCandidate, DiscoverResult } from "../../api/types";
import { MathText } from "../../math/MathText";
import { staggerRowsIn } from "../../motion/anime";

type RunState =
  | { phase: "idle" }
  | { phase: "running" }
  | { phase: "done"; candidates: DiscoverCandidate[] }
  | { phase: "error"; detail: string };

type AddPhase = "adding" | "added" | "error";

export function DiscoveryPanel({
  slug,
  onPapersChanged,
}: {
  slug: string;
  onPapersChanged: () => void;
}) {
  const api = useApi();
  const [run, setRun] = useState<RunState>({ phase: "idle" });
  const [added, setAdded] = useState<Record<string, AddPhase>>({});
  const [line, setLine] = useState("");

  // Candidate rows stagger in (40-60ms band, first 8, ≤600ms total —
  // the wrapper owns the caps and the reduced-motion gate).
  const listRef = useCallback((el: HTMLUListElement | null) => {
    if (el !== null) void staggerRowsIn(Array.from(el.children));
  }, []);

  async function runDiscovery() {
    setRun({ phase: "running" });
    setAdded({});
    setLine("Querying arXiv for candidates…");
    const { data, error, response } = await api.POST(
      "/api/v1/notebooks/{slug}/discover",
      { params: { path: { slug } } },
    );
    if (error !== undefined || data === undefined) {
      const detail =
        errorDetail(error) ??
        `POST /api/v1/notebooks/${slug}/discover failed (${response?.status ?? "network"}).`;
      setRun({ phase: "error", detail });
      setLine(detail);
      return;
    }
    const result = data as unknown as DiscoverResult;
    setRun({ phase: "done", candidates: result.candidates });
    setLine(
      `${result.count} candidate${result.count === 1 ? "" : "s"} proposed. Nothing persists until added.`,
    );
  }

  async function addCandidate(paperId: string) {
    setAdded((m) => ({ ...m, [paperId]: "adding" }));
    const { data, error, response } = await api.POST(
      "/api/v1/notebooks/{slug}/papers",
      {
        params: { path: { slug } },
        body: { arxiv_url: `https://arxiv.org/abs/${paperId}` },
      },
    );
    if (error !== undefined || data === undefined) {
      setAdded((m) => ({ ...m, [paperId]: "error" }));
      setLine(
        errorDetail(error) ??
          `POST /api/v1/notebooks/${slug}/papers failed (${response?.status ?? "network"}).`,
      );
      return;
    }
    setAdded((m) => ({ ...m, [paperId]: "added" }));
    setLine(`Added ${paperId} to the notebook.`);
    onPapersChanged();
  }

  return (
    <section aria-labelledby="discover-h">
      <div className="section-header">
        <h3 id="discover-h">Discovery</h3>
      </div>
      <p className="reg-editorial note-muted">
        Propose recent arXiv papers for this notebook's topic. The candidate
        queue is ephemeral — confirm each paper to add it.
      </p>
      <p>
        <button
          type="button"
          onClick={() => void runDiscovery()}
          disabled={run.phase === "running"}
        >
          Run discovery
        </button>
      </p>
      <p aria-live="polite" className="reg-telemetry" data-testid="discover-status">
        {line}
      </p>

      {run.phase === "done" && run.candidates.length > 0 && (
        <ul className="candidate-list" data-testid="candidate-list" ref={listRef}>
          {run.candidates.map((c) => {
            const phase = added[c.paper_id];
            return (
              <li key={c.paper_id} className="candidate">
                {/* Candidate prose comes from arXiv metadata and may
                    carry $TeX$ — the chunk-surface math track (D7). */}
                <div className="reg-editorial candidate-title">
                  <MathText text={c.title} />
                </div>
                <div className="reg-editorial note-muted">
                  <MathText text={c.abstract_head} />
                </div>
                <div className="notebook-meta reg-telemetry">
                  <span className="chip">{c.paper_id}</span>
                  <span className="note-muted">{c.submitted_date}</span>
                  <button
                    type="button"
                    onClick={() => void addCandidate(c.paper_id)}
                    disabled={phase === "adding" || phase === "added"}
                  >
                    {phase === "added" ? "Added" : "Add to notebook"}
                  </button>
                </div>
              </li>
            );
          })}
        </ul>
      )}

      {run.phase === "done" && run.candidates.length === 0 && (
        <div className="empty-state">
          <p>No new candidates for this topic window.</p>
          <p>Re-run later, or widen the topic description.</p>
        </div>
      )}
    </section>
  );
}
