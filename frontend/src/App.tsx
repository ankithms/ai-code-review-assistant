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
      <BrowserRouter>
        <RepositoryProvider>
          <div className="app-shell">
            <Navbar />
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
