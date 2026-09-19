/**
 * ApiProvider — dependency seam for the typed client.
 *
 * Pages consume the client through useApi() so component tests inject
 * makeClient(mockFetch) (IF-1 decoupling: every surface is testable
 * with zero live arXMCP process). The default is the app-wide
 * same-origin client — production code paths never change.
 */
import { createContext, useContext, type ReactNode } from "react";
import { api, type ApiClient } from "./client";

const ApiContext = createContext<ApiClient>(api);

export function ApiProvider({
  client,
  children,
}: {
  client: ApiClient;
  children: ReactNode;
}) {
  return <ApiContext.Provider value={client}>{children}</ApiContext.Provider>;
}

export function useApi(): ApiClient {
  return useContext(ApiContext);
}
