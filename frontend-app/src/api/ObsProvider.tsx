/**
 * ObsProvider — dependency seam for the observability read-API client
 * (the ApiProvider pattern applied to the a23 surface): pages consume
 * through useObsApi() so component tests inject makeObsApi(mockFetch)
 * and never need a live server. The context default is the app-wide
 * same-origin client — production code paths never change.
 */
import { createContext, useContext, type ReactNode } from "react";
import { obsApi, type ObsApi } from "./obs";

const ObsContext = createContext<ObsApi>(obsApi);

export function ObsProvider({
  api,
  children,
}: {
  api: ObsApi;
  children: ReactNode;
}) {
  return <ObsContext.Provider value={api}>{children}</ObsContext.Provider>;
}

export function useObsApi(): ObsApi {
  return useContext(ObsContext);
}
