import { useNavigate, useSearch } from "@tanstack/react-router";
import { Eye, EyeOff } from "lucide-react";
import { type FormEvent, useEffect, useState } from "react";

import { ApiError, apiFetch } from "@/api/client";
import { ApgarMark } from "@/components/ApgarMark";
import { ThemeToggle } from "@/components/ThemeToggle";
import { VerdictBadge } from "@/components/VerdictBadge";

const GITHUB_MARK =
  "M12 .297c-6.63 0-12 5.373-12 12 0 5.303 3.438 9.8 8.205 11.385.6.113.82-.258.82-.577 0-.285-.01-1.04-.015-2.04-3.338.724-4.042-1.61-4.042-1.61C4.422 18.07 3.633 17.7 3.633 17.7c-1.087-.744.084-.729.084-.729 1.205.084 1.838 1.236 1.838 1.236 1.07 1.835 2.809 1.305 3.495.998.108-.776.417-1.305.76-1.605-2.665-.3-5.466-1.332-5.466-5.93 0-1.31.465-2.38 1.235-3.22-.135-.303-.54-1.523.105-3.176 0 0 1.005-.322 3.3 1.23.96-.267 1.98-.399 3-.405 1.02.006 2.04.138 3 .405 2.28-1.552 3.285-1.23 3.285-1.23.645 1.653.24 2.873.12 3.176.765.84 1.23 1.91 1.23 3.22 0 4.61-2.805 5.625-5.475 5.92.42.36.81 1.096.81 2.22 0 1.606-.015 2.896-.015 3.286 0 .315.21.69.825.57C20.565 22.092 24 17.592 24 12.297c0-6.627-5.373-12-12-12";

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
            href="https://github.com/oimo-ai/apgar"
            target="_blank"
            rel="noreferrer"
            aria-label="Apgar on GitHub"
            title="Apgar on GitHub"
          >
            <svg viewBox="0 0 24 24" width={16} height={16} fill="currentColor" aria-hidden="true">
              <path d={GITHUB_MARK} />
            </svg>
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
