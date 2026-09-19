/**
 * Self-hosted WOFF2 registers (brief §2): STIX Two Text/Math editorial,
 * JetBrains Mono telemetry. Fontsource packages resolve to woff2 files
 * that Vite emits into dist/assets — served same-origin under
 * font-src 'self', zero network fetches (AC-B.2).
 *
 * The old roadmap's no-web-font rule is deliberately departed from:
 * its rationale (CSP widening + network fetch) is fully avoided by
 * self-hosting (brief §2 header).
 */
import "@fontsource/stix-two-text/400.css";
import "@fontsource/stix-two-text/400-italic.css";
import "@fontsource/stix-two-text/600.css";
import "@fontsource/stix-two-math/400.css";
import "@fontsource/jetbrains-mono/400.css";
import "@fontsource/jetbrains-mono/700.css";
