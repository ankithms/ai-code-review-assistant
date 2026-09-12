import { useEffect, useState, type ReactNode } from "react";
import {
  ArrowRight,
  Bot,
  CheckCircle2,
  GitBranch,
  LoaderCircle,
  SearchCode,
  ShieldCheck,
  Sparkles,
} from "lucide-react";

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
    return (
      <main className="auth-screen auth-screen--loading">
        <span className="auth-loader"><LoaderCircle aria-hidden="true" className="spin" size={22} /></span>
        <strong>Preparing your review workspace</strong>
        <span>Checking your session…</span>
      </main>
    );
  }

  if (state.status === "unauthenticated") {
    return (
      <main className="auth-screen">
        <div className="auth-glow auth-glow--one" aria-hidden="true" />
        <div className="auth-glow auth-glow--two" aria-hidden="true" />
        <section className="auth-layout">
          <div className="auth-story">
            <span className="auth-brand"><span><Sparkles aria-hidden="true" size={19} /></span> Review Lab</span>
            <p className="eyebrow">AI code intelligence</p>
            <h1>Ship confident code.<br /><em>Review at light speed.</em></h1>
            <p className="auth-story__lead">Turn pull requests into clear, prioritized findings—and move safely from issue to verified fix.</p>

            <div className="auth-features">
              <span><SearchCode aria-hidden="true" size={16} /> Risk-aware review</span>
              <span><Bot aria-hidden="true" size={16} /> AI fix workflow</span>
              <span><ShieldCheck aria-hidden="true" size={16} /> Validation built in</span>
            </div>

            <div className="auth-preview" aria-label="Example code review finding">
              <div className="auth-preview__top"><span><i /> review-agent</span><small>completed in 4.8s</small></div>
              <div className="auth-preview__code">
                <code><span>31</span> order = db.query(Order).filter_by(id=order_id)</code>
                <code className="auth-preview__finding"><span><ShieldCheck size={13} /></span> Ownership check missing · High priority</code>
              </div>
              <div className="auth-preview__result"><CheckCircle2 aria-hidden="true" size={16} /> Suggested fix validated</div>
            </div>
          </div>

          <div className="auth-card">
            <span className="auth-card__icon"><GitBranch aria-hidden="true" size={22} /></span>
            <p className="eyebrow">Welcome back</p>
            <h2>Open your review workspace</h2>
            <p>Connect with the GitHub account authorized for this instance.</p>
            <a className="auth-button button-with-icon" href={`${apiBaseUrl}/auth/github/login`}>
              <GitBranch aria-hidden="true" size={17} /> Continue with GitHub <ArrowRight aria-hidden="true" size={15} />
            </a>
            <div className="auth-divider"><span>or explore safely</span></div>
            <a className="secondary-button auth-demo-button button-with-icon" href="/demo/">
              <Sparkles aria-hidden="true" size={16} /> Try demo
            </a>
            <p className="auth-card__note">No account needed for the interactive sample.</p>
          </div>
        </section>
      </main>
    );
  }

  if (state.status === "error") {
    return (
      <main className="auth-screen">
        <section className="auth-card auth-card--centered">
          <span className="auth-card__icon"><Sparkles aria-hidden="true" size={22} /></span>
          <h1>Authentication service unavailable</h1>
          <p>You can still explore the sample dashboard.</p>
          <a className="auth-button button-with-icon" href="/demo/">Try demo <ArrowRight aria-hidden="true" size={15} /></a>
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
