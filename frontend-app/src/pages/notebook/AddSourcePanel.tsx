/**
 * Unified "add source" panel (brief §7.2): ONE entry point for every
 * source form — arXiv abs URL, native arxiv.org/html URL, ar5iv URL,
 * bare arXiv id (URL leg), or a file upload (ar5iv HTML for
 * arxiv-kind notebooks, PDF for textbook-kind). The classifier
 * (src/api/sources.ts) routes each to the right backend call and
 * renders an inline per-URL validation state before any network I/O.
 *
 * Degrade path (documented, tested): the A1 API spine rejects native
 * arxiv.org/html URLs with 422 (host/prefix whitelist predates the
 * arx-a45 fetch rung). On that exact signature the panel retries with
 * the canonical abs form — lossless, because the junction row stores
 * only the paper_id and the server-side fetch ladder chooses the HTML
 * rung on its own — and says so honestly in the status line.
 *
 * Upload leg: XHR with upload.onprogress driving a determinate bar
 * (monotone width, --motion-dur-2 standard ease; announcements are
 * per PHASE through the mounted aria-live line, never per tick).
 */
import { useId, useRef, useState } from "react";
import { useApi } from "../../api/ApiProvider";
import { errorDetail } from "../../api/errors";
import {
  absUrl,
  classifySource,
  describeSource,
  isValidArxivId,
} from "../../api/sources";
import { uploadPaper, type XhrFactory } from "../../api/upload";

const TEXTBOOK_ID_RE = /^textbook:[a-z][a-z0-9-]{2,30}$/;

/** Client-side mirrors of the server caps (server stays authoritative). */
const ARXIV_UPLOAD_MAX_BYTES = 10 * 1024 * 1024;
const TEXTBOOK_UPLOAD_MAX_BYTES = 200 * 1024 * 1024;

type Busy = "idle" | "url" | "upload";

export function AddSourcePanel({
  slug,
  notebookKind,
  onAdded,
  xhrFactory,
}: {
  slug: string;
  notebookKind: string;
  onAdded: () => void;
  /** Test seam for the XHR uploader. */
  xhrFactory?: XhrFactory;
}) {
  const api = useApi();
  const isTextbook = notebookKind === "textbook";
  const ids = useId();
  const [source, setSource] = useState("");
  const [paperId, setPaperId] = useState("");
  const [busy, setBusy] = useState<Busy>("idle");
  const [line, setLine] = useState("");
  const [pct, setPct] = useState<number | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  const cls = classifySource(source);
  const hint = source.trim() === "" ? "" : describeSource(cls);

  async function postUrl(arxivUrl: string) {
    return api.POST("/api/v1/notebooks/{slug}/papers", {
      params: { path: { slug } },
      body: { arxiv_url: arxivUrl },
    });
  }

  async function submitUrl() {
    if (cls.kind === "invalid") {
      setLine(cls.reason);
      return;
    }
    setBusy("url");
    setLine(`Adding ${cls.paperId}…`);
    const first = await postUrl(cls.arxivUrl);
    if (first.error === undefined && first.data !== undefined) {
      setLine(`Added ${cls.paperId}.`);
      setSource("");
      setBusy("idle");
      onAdded();
      return;
    }
    if (cls.kind === "native-html" && first.response?.status === 422) {
      // A1-spine degrade: record via the canonical abs form instead.
      const retry = await postUrl(absUrl(cls.paperId));
      if (retry.error === undefined && retry.data !== undefined) {
        setLine(
          `Added ${cls.paperId}. This server build does not accept ` +
            `arxiv.org/html URLs yet — recorded via the abs form; ingest ` +
            `fetches the HTML rendition server-side.`,
        );
        setSource("");
        setBusy("idle");
        onAdded();
        return;
      }
      setLine(
        errorDetail(retry.error) ??
          `POST /api/v1/notebooks/${slug}/papers failed (${retry.response?.status ?? "network"}).`,
      );
      setBusy("idle");
      return;
    }
    setLine(
      errorDetail(first.error) ??
        `POST /api/v1/notebooks/${slug}/papers failed (${first.response?.status ?? "network"}).`,
    );
    setBusy("idle");
  }

  /** Prefill the paper-id field from an id-shaped filename stem. */
  function onFilePicked() {
    const file = fileRef.current?.files?.[0];
    if (file === undefined || paperId !== "") return;
    const stem = file.name.replace(/\.(html?|pdf)$/i, "");
    if (isValidArxivId(stem) || TEXTBOOK_ID_RE.test(stem)) setPaperId(stem);
  }

  function validUploadId(id: string): boolean {
    return isTextbook
      ? isValidArxivId(id) || TEXTBOOK_ID_RE.test(id)
      : isValidArxivId(id);
  }

  async function submitUpload() {
    const file = fileRef.current?.files?.[0];
    if (file === undefined) {
      setLine("Choose a file to upload.");
      return;
    }
    const id = paperId.trim();
    if (!validUploadId(id)) {
      setLine(
        isTextbook
          ? `paper id ${JSON.stringify(id)} is not a valid arXiv id or textbook:<slug> form.`
          : `paper id ${JSON.stringify(id)} is not a valid arXiv id (e.g. 2401.00001).`,
      );
      return;
    }
    const cap = isTextbook ? TEXTBOOK_UPLOAD_MAX_BYTES : ARXIV_UPLOAD_MAX_BYTES;
    if (file.size > cap) {
      setLine(
        `${file.name} is ${file.size} bytes — over the ` +
          `${cap / (1024 * 1024)} MB cap for ${notebookKind}-kind notebooks.`,
      );
      return;
    }
    setBusy("upload");
    setPct(0);
    setLine(`Uploading ${file.name}…`);
    try {
      const outcome = await uploadPaper({
        slug,
        paperId: id,
        file,
        onProgress: (fraction) => setPct(Math.round(fraction * 100)),
        xhrFactory,
      });
      if (outcome.status === 200 || outcome.status === 201) {
        const result = outcome.body?.result === "updated_existing"
          ? "replaced the stored copy"
          : "created";
        setLine(`Uploaded ${id} (${result}).`);
        setPaperId("");
        if (fileRef.current !== null) fileRef.current.value = "";
        onAdded();
      } else {
        setLine(
          errorDetail(outcome.body) ??
            `Upload failed (${outcome.status}).`,
        );
      }
    } catch (e) {
      setLine(e instanceof Error ? e.message : "Upload failed.");
    } finally {
      setBusy("idle");
      setPct(null);
    }
  }

  return (
    <section aria-labelledby={`${ids}-h`}>
      <div className="section-header">
        <h3 id={`${ids}-h`}>Add source</h3>
      </div>

      <div className="form-row">
        <div className="field field-wide">
          <label htmlFor={`${ids}-url`}>arXiv URL or paper id</label>
          <input
            id={`${ids}-url`}
            type="text"
            value={source}
            placeholder="https://arxiv.org/abs/2401.00001"
            onChange={(e) => setSource(e.target.value)}
            disabled={busy !== "idle"}
          />
        </div>
        <button
          type="button"
          onClick={() => void submitUrl()}
          disabled={busy !== "idle" || source.trim() === ""}
        >
          Add paper
        </button>
      </div>
      <p className="reg-telemetry note-muted" data-testid="source-hint">
        {hint}
      </p>

      <p className="reg-telemetry note-muted">or upload a file —</p>

      <div className="form-row">
        <div className="field">
          <label htmlFor={`${ids}-pid`}>paper id</label>
          <input
            id={`${ids}-pid`}
            type="text"
            value={paperId}
            placeholder={isTextbook ? "textbook:my-slug or 2401.00001" : "2401.00001"}
            onChange={(e) => setPaperId(e.target.value)}
            disabled={busy !== "idle"}
          />
        </div>
        <div className="field field-wide">
          <label htmlFor={`${ids}-file`}>
            {isTextbook ? "PDF file (≤200 MB)" : "ar5iv/LaTeXML HTML file (≤10 MB)"}
          </label>
          <input
            id={`${ids}-file`}
            type="file"
            ref={fileRef}
            accept={isTextbook ? ".pdf,application/pdf" : ".html,.htm,text/html"}
            onChange={onFilePicked}
            disabled={busy !== "idle"}
          />
        </div>
        <button
          type="button"
          onClick={() => void submitUpload()}
          disabled={busy !== "idle"}
        >
          Upload
        </button>
      </div>

      {pct !== null && (
        <div
          className="progress-track"
          role="progressbar"
          aria-label="Upload progress"
          aria-valuemin={0}
          aria-valuemax={100}
          aria-valuenow={pct}
          data-testid="upload-progress"
        >
          <div className="progress-fill" style={{ width: `${pct}%` }} />
        </div>
      )}

      <p aria-live="polite" className="reg-telemetry" data-testid="addsource-status">
        {line}
      </p>
    </section>
  );
}
