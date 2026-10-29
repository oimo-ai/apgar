import { Link, Outlet, useNavigate, useParams, useRouterState } from "@tanstack/react-router";
import { BookOpen, Bot, Settings } from "lucide-react";
import { useEffect } from "react";

import { apiFetch } from "@/api/client";
import { useAgent } from "@/api/queries";
import { ApgarMark } from "@/components/ApgarMark";
import { DegradedBanner } from "@/components/DegradedBanner";
import { DemoBadge } from "@/components/DemoBadge";
import { GitHubMark } from "@/components/GitHubMark";
import { ThemeToggle } from "@/components/ThemeToggle";
import { DOCS_URL, GITHUB_URL } from "@/lib/links";
import { readChoice } from "@/lib/theme";
import { cn } from "@/lib/utils";

const NAV = [
  { to: "/", label: "Agents", testId: "nav-agents", icon: Bot },
  { to: "/settings", label: "Settings", testId: "nav-settings", icon: Settings },
] as const;

function isActive(pathname: string, to: string): boolean {
  if (to === "/") {
    return pathname === "/" || pathname.startsWith("/agents/");
  }
  return pathname === to || pathname.startsWith(`${to}/`);
}

function pageTitle(pathname: string): string {
  if (pathname === "/") {
    return "Agents";
  }
  if (pathname.startsWith("/settings")) {
    return "Settings";
  }
  if (pathname.includes("/releases/")) {
    return "Release";
  }
  if (pathname.startsWith("/agents/")) {
    return "Agent";
  }
  return "Apgar";
}

export function AppLayout() {
  const navigate = useNavigate();
  const pathname = useRouterState({ select: (state) => state.location.pathname });
  const params = useParams({ strict: false });
  const agentName = typeof params.agent === "string" ? params.agent : "";
  const agent = useAgent(agentName);

  useEffect(() => {
    const choice = readChoice();
    document.documentElement.dataset.theme = document.documentElement.dataset.theme || (choice === "dark" || choice === "light" ? choice : document.documentElement.dataset.theme);
  }, []);

  const title = pageTitle(pathname);

  return (
    <div className="app-shell">
      <div className="app-frame">
        <nav className="app-sidebar" aria-label="Primary">
          <div className="app-brand">
            <ApgarMark />
            <div>
              <p className="app-brand-name">Apgar</p>
              <p className="app-brand-sub">Release health</p>
            </div>
          </div>
          <div className="app-nav">
            {NAV.map(({ to, label, testId, icon: Icon }) => {
              const active = isActive(pathname, to);
              return (
                <Link
                  key={testId}
                  to={to}
                  data-testid={testId}
                  aria-current={active ? "page" : undefined}
                  className={cn("app-nav-link", active && "app-nav-link-active", to === "/settings" && "app-nav-bottom")}
                >
                  <Icon size={16} strokeWidth={1.75} aria-hidden="true" />
                  {label}
                </Link>
              );
            })}
          </div>
          <div className="app-sidebar-foot">
            <span data-testid="sidebar-version">Self hosted · v{__APP_VERSION__}</span>
            <div className="app-sidebar-links">
              <a
                data-testid="sidebar-docs"
                className="app-sidebar-link"
                href={DOCS_URL}
                target="_blank"
                rel="noreferrer"
                aria-label="Apgar docs"
                title="Docs"
              >
                <BookOpen size={16} strokeWidth={1.75} aria-hidden="true" />
              </a>
              <a
                data-testid="sidebar-github"
                className="app-sidebar-link"
                href={GITHUB_URL}
                target="_blank"
                rel="noreferrer"
                aria-label="Apgar on GitHub"
                title="GitHub"
              >
                <GitHubMark />
              </a>
            </div>
          </div>
        </nav>
        <div className="app-main">
          <header className="app-topbar">
            <div className="app-crumbs">
              {agentName ? (
                <>
                  <Link to="/" className="text-muted-foreground hover:text-foreground hover:no-underline">
                    Agents
                  </Link>
                  <span aria-hidden="true">/</span>
                  {title === "Agent" ? null : (
                    <>
                      <Link to="/agents/$agent" params={{ agent: agentName }} className="text-muted-foreground hover:text-foreground hover:no-underline">
                        {agentName}
                      </Link>
                      <span aria-hidden="true">/</span>
                    </>
                  )}
                </>
              ) : null}
              <h1 className="app-crumbs-here">{title === "Agent" && agentName ? agentName : title}</h1>
              {agent.data?.is_demo ? <DemoBadge /> : null}
            </div>
            <div className="flex items-center gap-2">
              <ThemeToggle variant="status" />
              <button
                type="button"
                data-testid="logout-button"
                className="app-chip"
                onClick={() => {
                  void apiFetch("/api/v1/auth/logout", { method: "POST" }).then(() => {
                    void navigate({ to: "/login" });
                  });
                }}
              >
                Log out
              </button>
            </div>
          </header>
          <DegradedBanner />
          <main className="app-content">
            <Outlet />
          </main>
        </div>
      </div>
    </div>
  );
}
