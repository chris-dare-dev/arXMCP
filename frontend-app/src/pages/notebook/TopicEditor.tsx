/**
 * Topic editor [E] (brief §7.1): inline edit, OPTIMISTIC UI, aria-live
 * confirm. The parent applies the new values immediately on save; a
 * failed PATCH reverts them and surfaces the server detail. Category
 * options mirror _VALID_DISCOVERY_CATEGORIES (server-enforced enum;
 * empty string clears the topic).
 */
import { useState, type FormEvent } from "react";
import { useApi } from "../../api/ApiProvider";
import { errorDetail } from "../../api/errors";

const CATEGORIES = ["math.AG", "math.NT", "math-ph", "hep-th"] as const;

export function TopicEditor({
  slug,
  category,
  description,
  onSaved,
}: {
  slug: string;
  category: string | null;
  description: string | null;
  onSaved: (category: string | null, description: string | null) => void;
}) {
  const api = useApi();
  const [editing, setEditing] = useState(false);
  const [cat, setCat] = useState(category ?? "");
  const [desc, setDesc] = useState(description ?? "");
  const [line, setLine] = useState("");

  async function save(e: FormEvent) {
    e.preventDefault();
    const prev = { category, description };
    // Optimistic: apply immediately, revert on error (brief §7.1).
    onSaved(cat === "" ? null : cat, desc === "" ? null : desc);
    setEditing(false);
    setLine("Saving topic…");
    const { data, error, response } = await api.PATCH(
      "/api/v1/notebooks/{slug}/topic",
      {
        params: { path: { slug } },
        body: { discovery_category: cat, description: desc },
      },
    );
    if (error !== undefined || data === undefined) {
      onSaved(prev.category, prev.description);
      setLine(
        errorDetail(error) ??
          `PATCH /api/v1/notebooks/${slug}/topic failed (${response?.status ?? "network"}).`,
      );
      return;
    }
    setLine("Topic saved.");
  }

  return (
    <section aria-labelledby="topic-h">
      <div className="section-header">
        <h3 id="topic-h">Topic</h3>
      </div>

      {!editing && (
        <>
          <p className="reg-telemetry">
            {category !== null && category !== "" ? (
              <span className="chip">{category}</span>
            ) : (
              <span className="note-muted">no category declared</span>
            )}
          </p>
          {description !== null && description !== "" && (
            <p className="reg-editorial">{description}</p>
          )}
          <p>
            <button
              type="button"
              onClick={() => {
                setCat(category ?? "");
                setDesc(description ?? "");
                setEditing(true);
              }}
            >
              Edit topic
            </button>
          </p>
        </>
      )}

      {editing && (
        <form onSubmit={(e) => void save(e)}>
          <div className="form-row">
            <div className="field">
              <label htmlFor="topic-category">category</label>
              <select
                id="topic-category"
                value={cat}
                onChange={(e) => setCat(e.target.value)}
              >
                <option value="">(none)</option>
                {CATEGORIES.map((c) => (
                  <option key={c} value={c}>
                    {c}
                  </option>
                ))}
              </select>
            </div>
            <div className="field field-wide">
              <label htmlFor="topic-description">description</label>
              <input
                id="topic-description"
                type="text"
                maxLength={512}
                value={desc}
                onChange={(e) => setDesc(e.target.value)}
              />
            </div>
            <button type="submit">Save topic</button>
            <button type="button" onClick={() => setEditing(false)}>
              Cancel
            </button>
          </div>
        </form>
      )}

      <p aria-live="polite" className="reg-telemetry" data-testid="topic-status">
        {line}
      </p>
    </section>
  );
}
