import { isDemoMode } from "./demo/mode";
import { resetDemoState } from "./demo/adapter";
import { ArrowRight, FlaskConical, RotateCcw } from "lucide-react";
import { Link } from "react-router-dom";
import {
  BrowserRouter,
  Routes,
  Route,
  useLocation,
} from "react-router-dom";

import PullRequests from "./pages/PullRequests";
import Dashboard from "./pages/Dashboard";
import Reviews from "./pages/Reviews";
import ReviewDetail from "./pages/ReviewDetail";
import Navbar from "./components/NavBar";
import { AuthGate } from "./auth/AuthGate";
import { RepositoryProvider } from "./context/RepositoryContext";

function AppRoutes() {
  const location = useLocation();

  return (
    <div className="route-stage" id="main-content" key={location.pathname} tabIndex={-1}>
      <Routes location={location}>
        <Route path="/" element={<Dashboard />} />
        <Route path="/reviews" element={<Reviews />} />
        <Route path="/reviews/:id" element={<ReviewDetail />} />
        <Route path="/pull-requests" element={<PullRequests />} />
        <Route
          path="*"
          element={(
            <main className="page">
              <section className="empty-state empty-state--large">
                <span className="empty-state__icon" aria-hidden="true">404</span>
                <h1>That review path does not exist</h1>
                <p>Return to the dashboard or browse the latest review activity.</p>
                <Link className="primary-button" to="/">Back to dashboard</Link>
              </section>
            </main>
          )}
        />
      </Routes>
    </div>
  );
}

function App() {
  return (
    <AuthGate>
      <BrowserRouter basename={isDemoMode() ? "/demo" : undefined}>
        <RepositoryProvider>
          <div className="app-shell">
            <Navbar />
            {isDemoMode() && (
              <aside className="demo-banner" aria-label="Demo workspace">
                <span className="demo-banner__label">
                  <FlaskConical aria-hidden="true" size={15} />
                  Interactive demo
                </span>
                <span className="demo-banner__copy">
                  Synthetic workspace · actions stay in this browser
                </span>
                <div className="demo-banner__links">
                  <Link to="/reviews/4">Try AI fix <ArrowRight aria-hidden="true" size={14} /></Link>
                  <Link to="/reviews/5">All categories</Link>
                  <Link to="/reviews/6">Lifecycle</Link>
                  <Link to="/reviews/1">Verified fix</Link>
                  <button
                    className="demo-banner__reset"
                    onClick={() => {
                      resetDemoState();
                      window.location.assign("/demo/");
                    }}
                    type="button"
                  >
                    <RotateCcw aria-hidden="true" size={13} /> Reset
                  </button>
                </div>
              </aside>
            )}
            <AppRoutes />
          </div>
        </RepositoryProvider>
      </BrowserRouter>
    </AuthGate>
  );
}

export default App;
