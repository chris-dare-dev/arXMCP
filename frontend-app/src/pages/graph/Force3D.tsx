/**
 * Force3D — the Tier-2 WebGL citation-graph view (arx-b3, AC-B.23).
 *
 * A thin lifecycle wrapper around 3d-force-graph (lazy chunk — this
 * module, three.js and the force engine parse only when GraphPage
 * renders it, AC-B.22). Discipline:
 *
 *  - freeze: <= 3 s engine cooldown (`cooldownTime(3000)`); under
 *    prefers-reduced-motion the layout is computed synchronously
 *    (warmup ticks) and rendered STATIC — zero animation frames.
 *  - camera: moves only on user action (drag/scroll). No auto-rotate,
 *    no programmatic fly-ins; the initial camera is set once without
 *    a tween.
 *  - palette: read from the live CSS tokens at mount, so the scene
 *    follows the OS light/dark scheme the rest of the app honors.
 *  - teardown: the WebGL context and engine are destroyed on unmount.
 *
 * The canvas is a visual complement, not the accessible surface —
 * GraphPage's Tier-0 list carries AT; the container is exposed as a
 * single labelled image with the data caption (NO-18).
 */
import ForceGraph3D from "3d-force-graph";
import { useEffect, useRef } from "react";

export interface Force3DNode {
  id: string;
  /** Paper has a representative chunk in the corpus (chunk_id set). */
  inCorpus: boolean;
}

export interface Force3DLink {
  source: string;
  target: string;
}

function cssToken(name: string, fallback: string): string {
  const v = getComputedStyle(document.documentElement)
    .getPropertyValue(name)
    .trim();
  return v === "" ? fallback : v;
}

export default function Force3D({
  nodes,
  links,
  caption,
  reducedMotion,
  height = 480,
}: {
  nodes: Force3DNode[];
  links: Force3DLink[];
  caption: string;
  reducedMotion: boolean;
  height?: number;
}) {
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const el = containerRef.current;
    if (el === null) return;

    const paper = cssToken("--paper", "#faf9f6");
    const ink = cssToken("--ink", "#1c1b18");
    const inkMuted = cssToken("--ink-muted", "#5c574c");
    const accent = cssToken("--accent", "#1e5b8a");

    const graph = new ForceGraph3D(el);
    graph
      .width(el.clientWidth || 640)
      .height(height)
      .backgroundColor(paper)
      .showNavInfo(false)
      .nodeRelSize(4)
      .nodeColor((n) => ((n as Force3DNode).inCorpus ? accent : ink))
      .nodeLabel((n) => {
        const node = n as Force3DNode;
        return `${node.id}${node.inCorpus ? " (in corpus)" : ""}`;
      })
      .linkColor(() => inkMuted)
      .linkOpacity(0.45)
      .enableNodeDrag(false)
      .graphData({
        nodes: nodes.map((n) => ({ ...n })),
        links: links.map((l) => ({ ...l })),
      });

    if (reducedMotion) {
      // Static settled layout: the engine runs synchronously before
      // the first frame; nothing animates afterwards (AC-B.16).
      graph.warmupTicks(120).cooldownTicks(0);
    } else {
      // AC-B.23: the layout freezes after at most 3 s.
      graph.cooldownTime(3000);
    }

    return () => {
      graph._destructor();
      el.replaceChildren();
    };
  }, [nodes, links, reducedMotion, height]);

  return (
    <figure className="force-3d-figure">
      <div
        ref={containerRef}
        className="force-3d-canvas"
        data-testid="force-3d"
        role="img"
        aria-label={`3-D force-directed citation graph: ${caption}. Visual complement to the neighbor list; drag rotates, scroll zooms.`}
      />
      <figcaption className="reg-telemetry" data-testid="force-3d-caption">
        {caption} — drag rotates · scroll zooms · right-drag pans
      </figcaption>
    </figure>
  );
}
