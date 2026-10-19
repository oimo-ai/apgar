import { useNavigate, useSearch } from "@tanstack/react-router";
import { Eye, EyeOff } from "lucide-react";
import { type FormEvent, useEffect, useState } from "react";

import { ApiError, apiFetch } from "@/api/client";
import { ApgarMark } from "@/components/ApgarMark";
import { ThemeToggle } from "@/components/ThemeToggle";

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
          <p className="login-kicker">Release health</p>
          <h1 className="login-headline">Did this release get worse?</h1>
          <p className="login-lede">
            Compare the release with its baseline. The verdict names what got worse, and where.
          </p>
          <aside className="login-example">
            <div className="login-example-top">
              <p className="login-example-kicker">Sample verdict</p>
              <span className="login-example-badge">FAIL</span>
            </div>
            <p className="login-example-agent">billing-copilot</p>
            <p className="login-example-id">fp-8e2f0c6a1b93</p>
            <div className="login-example-rows">
              <div className="login-example-row">
                <span>tool error rate</span>
                <span>above baseline</span>
              </div>
              <div className="login-example-row">
                <span>slice</span>
                <span className="login-mono">sql_query</span>
              </div>
            </div>
          </aside>
        </div>
        <p className="login-brand-foot">Self hosted. Prompt and completion text are not stored by default.</p>
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
          <p className="login-legal">Exchanged for a 24 hour HttpOnly cookie. The token is not kept in the page.</p>
        </div>
      </section>
    </div>
  );
}
