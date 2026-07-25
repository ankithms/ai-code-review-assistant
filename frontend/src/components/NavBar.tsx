import { NavLink } from "react-router-dom";
import { useRepository } from "../context/useRepository";

export default function Navbar() {
  const {
    repositories,
    selectedRepositoryId,
    setSelectedRepositoryId,
    loading,
  } = useRepository();

  return (
    <nav className="top-nav">
      <div className="top-nav__inner">
        <div className="brand">
          <div className="brand__mark">AI</div>

          <div>
            <p className="brand__title">Code Review Assistant</p>
            <p className="brand__subtitle">Repository quality dashboard</p>
          </div>
        </div>

        <div className="nav-links">
          <NavLink
            to="/"
            className={({ isActive }) =>
              isActive ? "nav-link nav-link--active" : "nav-link"
            }
          >
            Dashboard
          </NavLink>

          <NavLink
            to="/reviews"
            className={({ isActive }) =>
              isActive ? "nav-link nav-link--active" : "nav-link"
            }
          >
            Reviews
          </NavLink>

          <NavLink
            to="/pull-requests"
            className={({ isActive }) =>
              isActive ? "nav-link nav-link--active" : "nav-link"
            }
          >
            Pull Requests
          </NavLink>
        </div>

        <label className="repository-selector">
          <span>Repository</span>
          <select
            value={selectedRepositoryId ?? ""}
            disabled={loading || repositories.length === 0}
            onChange={(event) => {
              setSelectedRepositoryId(Number(event.target.value));
            }}
          >
            {repositories.length === 0 ? (
              <option value="">No repositories</option>
            ) : (
              repositories.map((repository) => (
                <option
                  key={repository.id}
                  value={repository.id}
                >
                  {repository.full_name}
                </option>
              ))
            )}
          </select>
        </label>
      </div>
    </nav>
  );
}
