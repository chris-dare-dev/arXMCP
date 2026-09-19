/**
 * GraphProvider — dependency seam for the citation-graph client (the
 * ApiProvider pattern applied to the a45 REST endpoint): pages consume
 * through useGraphApi() so component tests inject
 * makeGraphApi(mockFetch) and never need a live server. The context
 * default is the app-wide same-origin client — production code paths
 * never change.
 */
import { createContext, useContext, type ReactNode } from "react";
import { graphApi, type GraphApi } from "./graph";

const GraphContext = createContext<GraphApi>(graphApi);

export function GraphProvider({
  api,
  children,
}: {
  api: GraphApi;
  children: ReactNode;
}) {
  return <GraphContext.Provider value={api}>{children}</GraphContext.Provider>;
}

export function useGraphApi(): GraphApi {
  return useContext(GraphContext);
}
