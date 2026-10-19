import {
  createRootRoute,
  createRoute,
  createRouter,
  Outlet,
  redirect,
} from "@tanstack/react-router";

import { AppLayout } from "@/components/AppLayout";
import { AgentPage } from "@/pages/AgentPage";
import { AgentsPage } from "@/pages/AgentsPage";
import { LoginPage } from "@/pages/LoginPage";
import { ReleasePage } from "@/pages/ReleasePage";
import { SettingsPage } from "@/pages/SettingsPage";

const rootRoute = createRootRoute({
  component: Outlet,
});

const loginRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/login",
  validateSearch: (search: Record<string, unknown>): { redirect?: string } => ({
    redirect: typeof search.redirect === "string" ? search.redirect : undefined,
  }),
  component: LoginPage,
});

const authedRoute = createRoute({
  getParentRoute: () => rootRoute,
  id: "authed",
  beforeLoad: async ({ location }) => {
    const response = await fetch("/api/v1/auth/session", {
      credentials: "include",
      headers: { Accept: "application/json" },
    });
    if (response.status === 401) {
      throw redirect({
        to: "/login",
        search: { redirect: `${location.pathname}${location.searchStr}` },
      });
    }
  },
  component: AppLayout,
});

const agentsRoute = createRoute({
  getParentRoute: () => authedRoute,
  path: "/",
  validateSearch: (search: Record<string, unknown>): { add?: boolean } => ({
    add: search.add === true || search.add === "true" ? true : undefined,
  }),
  component: AgentsPage,
});

const agentRoute = createRoute({
  getParentRoute: () => authedRoute,
  path: "/agents/$agent",
  component: AgentPage,
});

const releaseRoute = createRoute({
  getParentRoute: () => authedRoute,
  path: "/agents/$agent/releases/$release",
  component: ReleasePage,
});

const addAgentRoute = createRoute({
  getParentRoute: () => authedRoute,
  path: "/add-agent",
  beforeLoad: () => {
    throw redirect({ to: "/", search: { add: true } });
  },
});

const settingsRoute = createRoute({
  getParentRoute: () => authedRoute,
  path: "/settings",
  validateSearch: (search: Record<string, unknown>): { tab: string; agent?: string; section?: string } => ({
    tab: typeof search.tab === "string" ? search.tab : "connections",
    ...(typeof search.agent === "string" ? { agent: search.agent } : {}),
    ...(typeof search.section === "string" ? { section: search.section } : {}),
  }),
  component: SettingsPage,
});

const routeTree = rootRoute.addChildren([
  loginRoute,
  authedRoute.addChildren([
    agentsRoute,
    agentRoute,
    releaseRoute,
    addAgentRoute,
    settingsRoute,
  ]),
]);

export const router = createRouter({ routeTree });

declare module "@tanstack/react-router" {
  interface Register {
    router: typeof router;
  }
}
