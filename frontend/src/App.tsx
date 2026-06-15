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

function App() {
  return (
    <BrowserRouter>
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
    </BrowserRouter>
  );
}

export default App;