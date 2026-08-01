/*
 * json-enc.js — minimal htmx 2.x extension that serialises a request's form
 * parameters as a JSON body. PROJECT-AUTHORED for arXMCP (ui-htmx-json-fix-m1);
 * NOT a third-party vendored asset (so it is not pinned in VENDORED.md /
 * tests/test_vendored_assets_integrity.py — same posture as app.css).
 *
 * Why this exists: the previous inline base.html shim set
 * `evt.detail.body = JSON.stringify(...)` on htmx:configRequest, but the
 * vendored htmx 2.0.10 has NO `evt.detail.body` hook — `encodeParameters`
 * is the real request-body override point (htmx uses its non-null return
 * value as the body bytes). The shim also cleared `evt.detail.parameters`,
 * so htmx serialised an empty parameter set → empty body → FastAPI 422 on
 * the create-notebook / add-paper / discover / ingest / rename / topic forms.
 *
 * htmx 2.0.10 passes the raw FormData as `parameters` (verified against the
 * vendored htmx.min.js: `wn(g,r,w)` -> `encodeParameters(xhr, w, elt)` where
 * the request detail carries `formData:w`). FormData is NOT JSON-serialisable
 * directly — `JSON.stringify(formData)` yields "{}" (that is the htmx-1.x
 * json-enc bug). So we iterate with `FormData.forEach(value, key)`.
 *
 * Attach per-form with `hx-ext="json-enc"`. Multipart uploads
 * (`hx-encoding="multipart/form-data"`) and bodyless DELETE controls MUST NOT
 * carry it — `hx-ext` inherits to descendants, so it is placed on individual
 * JSON forms, never on <body>.
 */
(function () {
  "use strict";
  if (typeof htmx === "undefined") {
    // Defensive: json-enc.js is loaded deferred AFTER htmx.min.js, so htmx is
    // always defined here in practice. The guard only prevents a hard error
    // if the load order is ever changed.
    return;
  }
  htmx.defineExtension("json-enc", {
    onEvent: function (name, evt) {
      if (name === "htmx:configRequest") {
        evt.detail.headers["Content-Type"] = "application/json";
      }
    },
    encodeParameters: function (xhr, parameters, elt) {
      xhr.overrideMimeType("text/json");
      var body = {};
      // `parameters` is a FormData (htmx 2.x) — iterate (value, key). Repeated
      // keys collapse into an array (defensive; the arXMCP forms have none).
      parameters.forEach(function (value, key) {
        if (Object.prototype.hasOwnProperty.call(body, key)) {
          if (!Array.isArray(body[key])) {
            body[key] = [body[key]];
          }
          body[key].push(value);
        } else {
          body[key] = value;
        }
      });
      return JSON.stringify(body);
    }
  });
})();
