import { useEffect, useState, type ReactNode } from "react";

import { api, apiBaseUrl } from "../services/api";
import { isDemoMode } from "../demo/mode";
import { AuthContext } from "./auth-context";

type AuthState =
  | { status: "loading" }
  | { status: "authenticated"; githubLogin: string }
  | { status: "unauthenticated" }
  | { status: "error" };

export function AuthGate({ children }: { children: ReactNode }) {
  const [state, setState] = useState<AuthState>({ status: "loading" });

  useEffect(() => {
    if (isDemoMode()) return;
    api.get("/auth/session")
      .then((response) => {
        setState({
          status: "authenticated",
          githubLogin: response.data.github_login,
        });
      })
      .catch((error: { response?: { status?: number } }) => {
        setState(
          error.response?.status === 401
            ? { status: "unauthenticated" }
            : { status: "error" }
        );
      });
  }, []);

  if (isDemoMode()) {
    return <AuthContext.Provider value={{ githubLogin: "Demo visitor", logout: async () => { window.location.assign("/"); } }}>{children}</AuthContext.Provider>;
  }

  if (state.status === "loading") {
    return <main className="auth-screen">Checking your session…</main>;
  }

  if (state.status === "unauthenticated") {
    return (
      <main className="auth-screen">
        <section className="auth-card">
          <p className="eyebrow">AI Code Review Assistant</p>
          <h1>Explore AI code reviews</h1>
          <p>Browse sample findings, code changes, and suggested fixes. No account needed.</p>
          <a className="auth-button" href="/demo/">Try demo</a>
          <p>Use the GitHub account authorized for this instance.</p>
          <a className="auth-button" href={`${apiBaseUrl}/auth/github/login`}>
            Continue with GitHub
          </a>
        </section>
      </main>
    );
  }

  if (state.status === "error") {
    return (
      <main className="auth-screen">
        <section className="auth-card">
          <h1>Authentication service unavailable</h1>
          <p>You can still explore the sample dashboard.</p>
          <a className="auth-button" href="/demo/">Try demo</a>
        </section>
      </main>
    );
  }

  const logout = async () => {
    await api.post("/auth/logout");
    window.location.assign("/");
  };

  return (
    <AuthContext.Provider value={{ githubLogin: state.githubLogin, logout }}>
      {children}
    </AuthContext.Provider>
  );
}
