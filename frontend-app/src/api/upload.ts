/**
 * XHR uploader for POST /api/v1/notebooks/{slug}/papers/upload.
 *
 * fetch() exposes no request-body progress, so the determinate upload
 * bar (brief §7.2 File upload: "XHR upload.onprogress determinate
 * bar") rides XMLHttpRequest. Same-origin relative URL keeps
 * connect-src 'self' (AC-B.2). The XHR constructor is injectable so
 * component tests drive progress/load/error events deterministically
 * (jsdom's XHR has no network).
 *
 * Server contract (server/routes/api_v1.py upload_paper_v1):
 *   multipart fields `paper_id` + `file`;
 *   201 {result:"created"} | 200 {result:"updated_existing"};
 *   413 over-cap (arxiv-kind 10 MB), 415 PDF preflight rejection,
 *   422 bad id / not-HTML, 409 never (upload is idempotent), 404 no
 *   notebook. Error bodies carry FastAPI {detail}.
 */

export interface UploadOutcome {
  status: number;
  /** Parsed JSON body, or null when the body was not JSON. */
  body: Record<string, unknown> | null;
}

export type XhrFactory = () => XMLHttpRequest;

export interface UploadArgs {
  slug: string;
  paperId: string;
  file: File;
  /** 0..1 fraction of request bytes sent (upload.onprogress). */
  onProgress?: (fraction: number) => void;
  /** Test seam; defaults to the real XMLHttpRequest. */
  xhrFactory?: XhrFactory;
}

export function uploadPaper({
  slug,
  paperId,
  file,
  onProgress,
  xhrFactory,
}: UploadArgs): Promise<UploadOutcome> {
  const xhr = (xhrFactory ?? (() => new XMLHttpRequest()))();
  const form = new FormData();
  form.append("paper_id", paperId);
  form.append("file", file, file.name);

  return new Promise<UploadOutcome>((resolve, reject) => {
    xhr.upload.addEventListener("progress", (ev: ProgressEvent) => {
      if (ev.lengthComputable && ev.total > 0) {
        onProgress?.(Math.min(1, ev.loaded / ev.total));
      }
    });
    xhr.addEventListener("load", () => {
      let body: Record<string, unknown> | null = null;
      try {
        body = JSON.parse(xhr.responseText) as Record<string, unknown>;
      } catch {
        body = null;
      }
      onProgress?.(1);
      resolve({ status: xhr.status, body });
    });
    xhr.addEventListener("error", () => {
      reject(new Error("upload failed: network error"));
    });
    xhr.addEventListener("abort", () => {
      reject(new Error("upload aborted"));
    });
    xhr.open(
      "POST",
      `/api/v1/notebooks/${encodeURIComponent(slug)}/papers/upload`,
    );
    xhr.send(form);
  });
}
