import { useNavigate, useSearch } from "@tanstack/react-router";
import { Eye, EyeOff } from "lucide-react";
import { type FormEvent, useEffect, useState } from "react";

import { ApiError, apiFetch } from "@/api/client";
import { ApgarMark } from "@/components/ApgarMark";
import { GitHubMark } from "@/components/GitHubMark";
import { ThemeToggle } from "@/components/ThemeToggle";
import { VerdictBadge } from "@/components/VerdictBadge";
import { GITHUB_URL } from "@/lib/links";

export function LoginPage() {
  const navigate = useNavigate();
  const search = useSearch({ strict: false });
  const redirect = typeof search.redirect === "string" ? search.redirect : "/";
  const [token, setToken] = useState("");
  const [visible, setVisible] = useState(false);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    const previous = document.title;
    document.title = "Log in · Apgar";
    return () => {
      document.title = previous;
    };
  }, []);

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    setError("");
    setPending(true);
    try {
      await apiFetch("/api/v1/auth/login", {
        method: "POST",
        body: JSON.stringify({ token }),
      });
      const target = redirect.startsWith("/") && !redirect.startsWith("//") ? redirect : "/";
      await navigate({ href: target });
    } catch (err) {
      if (err instanceof ApiError && err.status === 429) {
        setError("Too many attempts, wait a minute");
        return;
      }
      setError("Invalid token");
    } finally {
      setPending(false);
    }
  }

  return (
    <div data-testid="page-login" className="login-shell">
      <section className="login-brand" aria-label="About Apgar">
        <div className="login-wordmark">
          <ApgarMark />
          <span>Apgar</span>
        </div>
        <div className="login-brand-body">
          <p className="login-kicker">Release health for AI agents</p>
          <h1 className="login-headline">Did the latest release make your agent worse?</h1>
          <p className="login-lede">
            Apgar compares each new release with the one before it, using the traces you already collect, and shows
            what got worse and where.
          </p>
          <aside className="login-example" aria-label="Sample verdict">
            <div className="login-example-top">
              <p className="login-example-kicker">Sample verdict</p>
              <VerdictBadge state="FAIL" />
            </div>
            <p className="login-example-release">
              <span className="login-example-agent">billing-copilot</span>
              <span className="login-mono">v2.14.0</span>
            </p>
            <dl className="login-example-rows">
              <div className="login-example-row">
                <dt>Tool error rate</dt>
                <dd className="login-mono">
                  1.8%
                  <span aria-hidden="true"> → </span>
                  <span className="sr-only"> to </span>
                  <span className="login-example-fail">7.4%</span>
                </dd>
              </div>
              <div className="login-example-row">
                <dt>Concentrated in</dt>
                <dd className="login-mono">sql_query</dd>
              </div>
            </dl>
            <p className="login-example-basis">
              Based on 1,240 turns against 3,812 from <span className="login-mono">v2.13.2</span>.
            </p>
          </aside>
        </div>
        <div className="login-brand-foot">
          <span data-testid="login-version">Self hosted · v{__APP_VERSION__}</span>
          <a
            data-testid="login-github"
            className="login-github"
            href={GITHUB_URL}
            target="_blank"
            rel="noreferrer"
            aria-label="Apgar on GitHub"
            title="Apgar on GitHub"
          >
            <GitHubMark />
          </a>
        </div>
      </section>

      <section className="login-panel">
        <div className="login-toolbar">
          <ThemeToggle variant="status" />
        </div>
        <div className="login-card">
          <h2 className="login-title">Log in</h2>
          <p className="login-sub">Enter the admin token for this instance.</p>
          <form
            data-testid="login-form"
            className="login-form"
            aria-busy={pending}
            onSubmit={(event) => void onSubmit(event)}
          >
            <div className="login-field-block">
              <label className="login-label" htmlFor="admin-token">
                Admin token
              </label>
              <div className="login-control">
                <input
                  id="admin-token"
                  data-testid="login-token"
                  className="login-field"
                  type={visible ? "text" : "password"}
                  name="token"
                  autoComplete="current-password"
                  autoCapitalize="off"
                  autoCorrect="off"
                  spellCheck={false}
                  autoFocus
                  value={token}
                  aria-invalid={error ? true : undefined}
                  aria-describedby={error ? "login-error" : undefined}
                  onChange={(event) => setToken(event.target.value)}
                />
                <button
                  type="button"
                  className="login-reveal"
                  aria-label={visible ? "Hide token" : "Show token"}
                  aria-pressed={visible}
                  onClick={() => setVisible((value) => !value)}
                >
                  {visible ? <EyeOff size={16} strokeWidth={1.75} aria-hidden="true" /> : <Eye size={16} strokeWidth={1.75} aria-hidden="true" />}
                </button>
              </div>
              <p className="login-hint">
                The value of <span className="login-mono">APGAR_ADMIN_TOKEN</span>.
              </p>
            </div>
            {error ? (
              <p id="login-error" data-testid="login-error" role="alert" className="login-error">
                {error}
              </p>
            ) : null}
            <button
              type="submit"
              data-testid="login-submit"
              className="login-submit"
              data-pending={pending ? "true" : "false"}
              disabled={pending}
            >
              {pending ? <span className="login-spinner" aria-hidden="true" /> : null}
              {pending ? "Logging in" : "Log in"}
            </button>
          </form>
        </div>
      </section>
    </div>
  );
}
