/**
 * CapsProvider — dependency seam for the capability-profile client
 * (the ApiProvider pattern applied to the a23 CRUD surface): pages
 * consume through useCapsApi() so component tests inject
 * makeCapsApi(mockFetch) and never need a live server. The context
 * default is the app-wide same-origin client — production code paths
 * never change.
 */
import { createContext, useContext, type ReactNode } from "react";
import { capsApi, type CapsApi } from "./caps";

const CapsContext = createContext<CapsApi>(capsApi);

export function CapsProvider({
  api,
  children,
}: {
  api: CapsApi;
  children: ReactNode;
}) {
  return <CapsContext.Provider value={api}>{children}</CapsContext.Provider>;
}

export function useCapsApi(): CapsApi {
  return useContext(CapsContext);
}
