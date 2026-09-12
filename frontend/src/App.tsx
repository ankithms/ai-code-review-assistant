import { isDemoMode } from "./demo/mode";
import { ArrowRight, FlaskConical } from "lucide-react";
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
                  Sample data · GitHub actions are safely disabled
                </span>
                <div className="demo-banner__links">
                  <Link to="/reviews/4">Open findings <ArrowRight aria-hidden="true" size={14} /></Link>
                  <Link to="/reviews/1">Successful AI fix</Link>
                  <Link to="/reviews/3">Clean review</Link>
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
