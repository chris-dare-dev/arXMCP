/* arXMCP operator-console behaviour.
 *
 * Why this file exists (issues #431 / #432 / #433):
 *
 * The console used to carry its behaviour in 11 inline `hx-on::` attributes.
 * htmx compiles an `hx-on::` attribute body with `new Function()`, which the
 * console's own Content-Security-Policy forbids -- `server/middleware.py`'s
 * CONTENT_SECURITY_POLICY_UI grants `script-src 'self' 'unsafe-inline'` and
 * deliberately withholds `'unsafe-eval'`. Every one of those handlers threw
 * `EvalError` at parse time, so the UI had NO working error display and NO
 * post-success cleanup anywhere (#431), a failed create looked like a
 * success (#432), and a dead backend left a stale-but-healthy page (#433).
 *
 * The fix is delegation, not a CSP relaxation: `script-src 'self'` already
 * admits this file, so nothing here needs `eval` and adding `'unsafe-eval'`
 * would have pushed the policy the wrong way -- see #483, which wants
 * `'unsafe-inline'` dropped as well. Templates now DECLARE their intent in
 * data attributes and the listeners below act on it.
 *
 * Template contract
 * -----------------
 *   data-error-target="<element id>"
 *       Where this element's failure text goes. Written on a 4xx/5xx, and
 *       cleared when the same element starts a new request, so a retry never
 *       shows the previous attempt's message.
 *
 *   data-on-success="<token> <token> ..."   (only runs when the request
 *                                            actually succeeded)
 *       reset                     -- form.reset()
 *       remove:<selector>         -- remove the first document match
 *       remove-closest:<selector> -- remove the nearest matching ancestor
 *       navigate:<url>            -- window.location.href = url
 *
 * Everything is registered once, on <body>, because htmx events bubble.
 * That keeps the handlers alive across swaps: an element htmx injects later
 * is covered without re-binding, which an inline attribute could never do.
 */
(function () {
  "use strict";

  var OFFLINE_MESSAGE =
    "Cannot reach the arXMCP server. It may have stopped — check that it is still running.";

  /* ---------------------------------------------------------------- utils */

  /* FastAPI errors arrive as {"detail": "..."}; anything else (an HTML error
   * page, a proxy's plain text) is shown verbatim rather than swallowed. */
  function messageFrom(xhr) {
    var raw = (xhr && xhr.responseText) || "";
    try {
      var parsed = JSON.parse(raw);
      if (parsed && typeof parsed.detail === "string") {
        return parsed.detail;
      }
      if (parsed && parsed.detail) {
        return JSON.stringify(parsed.detail);
      }
    } catch (err) {
      /* not JSON -- fall through to the raw body */
    }
    return raw;
  }

  function errorTargetOf(elt) {
    if (!elt || !elt.getAttribute) {
      return null;
    }
    var id = elt.getAttribute("data-error-target");
    return id ? document.getElementById(id) : null;
  }

  function showError(elt, text) {
    var target = errorTargetOf(elt);
    if (target) {
      /* textContent, never innerHTML: the body is server- or
       * network-controlled and must not be parsed as markup. */
      target.textContent = text;
    }
  }

  /* ------------------------------------------------- connection-lost state */

  function connectionBanner() {
    return document.getElementById("connection-lost");
  }

  function setOffline(isOffline) {
    var banner = connectionBanner();
    if (banner) {
      banner.hidden = !isOffline;
    }
    var badge = document.getElementById("status-badge");
    if (!badge) {
      return;
    }
    if (isOffline) {
      /* Text and class only -- NEVER replace the element. The badge carries
       * its own hx-get/hx-trigger="every 10s", so leaving the node in place
       * is what lets it recover on its own once the server answers again
       * (the next successful poll swaps in a fresh fragment). */
      badge.className = "status-badge status-badge--down";
      badge.textContent = "DOWN | server unreachable";
    }
  }

  /* -------------------------------------------------- success token runner */

  function runSuccessTokens(elt) {
    var spec = elt.getAttribute("data-on-success");
    if (!spec) {
      return;
    }
    spec.split(/\s+/).forEach(function (token) {
      if (!token) {
        return;
      }
      var split = token.indexOf(":");
      var name = split === -1 ? token : token.slice(0, split);
      var arg = split === -1 ? "" : token.slice(split + 1);

      if (name === "reset" && typeof elt.reset === "function") {
        elt.reset();
      } else if (name === "remove" && arg) {
        var found = document.querySelector(arg);
        if (found) {
          found.remove();
        }
      } else if (name === "remove-closest" && arg) {
        var ancestor = elt.closest(arg);
        if (ancestor) {
          ancestor.remove();
        }
      } else if (name === "navigate" && arg) {
        window.location.href = arg;
      }
    });
  }

  /* ------------------------------------------------------------ listeners */

  document.body.addEventListener("htmx:beforeRequest", function (evt) {
    showError(evt.detail.elt, "");
  });

  /* The server answered, with a 4xx or 5xx. */
  document.body.addEventListener("htmx:responseError", function (evt) {
    var text = messageFrom(evt.detail.xhr);
    showError(
      evt.detail.elt,
      text || "Request failed (HTTP " + evt.detail.xhr.status + ")."
    );
  });

  /* The server did not answer at all -- refused, reset, or DNS-dead.
   * htmx emits sendError (NOT responseError) here, which is exactly why
   * #433 survived every response-error handler the templates had. */
  document.body.addEventListener("htmx:sendError", function (evt) {
    showError(evt.detail.elt, OFFLINE_MESSAGE);
    setOffline(true);
  });

  document.body.addEventListener("htmx:afterRequest", function (evt) {
    if (!evt.detail.successful) {
      return;
    }
    /* Any successful exchange proves the server is back. */
    setOffline(false);
    runSuccessTokens(evt.detail.elt);
  });

  /* ------------------------------------------------ view-transition toggle */

  /* Moved here from an inline <script> in base.html. Same behaviour, same
   * reasoning as before: `defer` is ignored on inline scripts, so the old
   * block ran before htmx existed; a DOMContentLoaded handler runs after
   * deferred scripts. The preference is re-read on `change` so an operator
   * flipping reduced-motion mid-session is honoured without a reload.
   * It lives in this file now so the console has exactly one behaviour
   * script and no inline one -- which is what #483 needs in order to drop
   * `'unsafe-inline'` from script-src. */
  document.addEventListener("DOMContentLoaded", function () {
    if (typeof htmx === "undefined") {
      return;
    }
    var mq = window.matchMedia("(prefers-reduced-motion: reduce)");
    var apply = function () {
      htmx.config.globalViewTransitions = !mq.matches;
    };
    apply();
    mq.addEventListener("change", apply);
  });
})();
