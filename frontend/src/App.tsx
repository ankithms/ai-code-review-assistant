import { isDemoMode } from "./demo/mode";
import { Link } from "react-router-dom";
import {
  BrowserRouter,
  Routes,
  Route,
} from "react-router-dom";

import PullRequests from "./pages/PullRequests";
import Dashboard from "./pages/Dashboard";
import Reviews from "./pages/Reviews";
import ReviewDetail from "./pages/ReviewDetail";
import Navbar from "./components/NavBar";
import { AuthGate } from "./auth/AuthGate";
import { RepositoryProvider } from "./context/RepositoryContext";

function App() {
  return (
    <AuthGate>
      <BrowserRouter basename={isDemoMode() ? "/demo" : undefined}>
        <RepositoryProvider>
          <div className="app-shell">
            <Navbar />
            {isDemoMode() && <aside className="demo-banner" aria-label="Demo workspace">
              <strong>Read-only demo</strong>
              <span>Illustrative sample data. Live reviews and GitHub actions are disabled.</span>
              <Link to="/reviews/1">Explore a sample review →</Link>
              <Link to="/reviews/4">See unresolved findings →</Link>
            </aside>}
            <Routes>
              <Route
                path="/"
                element={<Dashboard />}
              />

              <Route
                path="/reviews"
                element={<Reviews />}
              />
              <Route
                path="/reviews/:id"
                element={<ReviewDetail />}
              />
              <Route
                path="/pull-requests"
                element={<PullRequests />}
              />
            </Routes>
          </div>
        </RepositoryProvider>
      </BrowserRouter>
    </AuthGate>
  );
}

export default App;
