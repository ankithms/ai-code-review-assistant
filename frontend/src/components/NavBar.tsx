import { isDemoMode } from "../demo/mode";
import {
  Command,
  GitPullRequest,
  LayoutDashboard,
  LogOut,
  Moon,
  SearchCode,
  Sparkles,
  Sun,
} from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { Link, NavLink } from "react-router-dom";
import { useAuth } from "../auth/auth-context";
import { useRepository } from "../context/useRepository";
import CommandPalette from "./CommandPalette";

const navItems = [
  { to: "/", label: "Dashboard", icon: LayoutDashboard, end: true },
  { to: "/reviews", label: "Reviews", icon: SearchCode, end: false },
  { to: "/pull-requests", label: "Pull Requests", icon: GitPullRequest, end: false },
];

export default function Navbar() {
  const {
    repositories,
    selectedRepositoryId,
    setSelectedRepositoryId,
    loading,
  } = useRepository();
  const { githubLogin, logout } = useAuth();
  const [commandOpen, setCommandOpen] = useState(false);
  const [theme, setTheme] = useState<"light" | "dark">(() => {
    const saved = window.localStorage.getItem("review-lab-theme");
    return saved === "dark" ? "dark" : "light";
  });

  const closeCommand = useCallback(() => setCommandOpen(false), []);

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    window.localStorage.setItem("review-lab-theme", theme);
  }, [theme]);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        setCommandOpen((open) => !open);
      }
    };

    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, []);

  return (
    <>
      <a className="skip-link" href="#main-content">Skip to content</a>
      <nav aria-label="Primary navigation" className="top-nav">
        <div className="top-nav__inner">
          <Link aria-label="Review Lab dashboard" className="brand" to="/">
            <span className="brand__mark" aria-hidden="true">
              <Sparkles size={19} strokeWidth={2.25} />
            </span>

            <span>
              <span className="brand__title">Review Lab</span>
              <span className="brand__subtitle">AI code intelligence</span>
            </span>
          </Link>

          <div className="nav-links">
            {navItems.map(({ to, label, icon: Icon, end }) => (
              <NavLink
                end={end}
                key={to}
                to={to}
                className={({ isActive }) =>
                  isActive ? "nav-link nav-link--active" : "nav-link"
                }
              >
                <Icon aria-hidden="true" size={16} />
                <span>{label}</span>
              </NavLink>
            ))}
          </div>

          <div className="nav-tools">
            <label className="repository-selector">
              <span className="repository-selector__label">
                <i aria-hidden="true" /> Repository
              </span>
              <select
                aria-label="Selected repository"
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
                    <option key={repository.id} value={repository.id}>
                      {repository.full_name}
                    </option>
                  ))
                )}
              </select>
            </label>

            <button
              aria-label="Open quick navigation"
              className="nav-command"
              onClick={() => setCommandOpen(true)}
              title="Quick navigation (Ctrl or Command + K)"
              type="button"
            >
              <Command aria-hidden="true" size={16} />
              <kbd>⌘K</kbd>
            </button>

            <button
              aria-label={`Switch to ${theme === "light" ? "dark" : "light"} theme`}
              className="icon-button nav-icon-button"
              onClick={() => setTheme((current) => current === "light" ? "dark" : "light")}
              title={`Switch to ${theme === "light" ? "dark" : "light"} theme`}
              type="button"
            >
              {theme === "light"
                ? <Moon aria-hidden="true" size={17} />
                : <Sun aria-hidden="true" size={17} />}
            </button>

            <button
              aria-label={isDemoMode() ? "Exit demo" : `Sign out ${githubLogin}`}
              className="icon-button nav-icon-button nav-logout"
              onClick={() => void logout()}
              title={isDemoMode() ? "Exit demo" : `Sign out (${githubLogin})`}
              type="button"
            >
              <LogOut aria-hidden="true" size={17} />
            </button>
          </div>
        </div>
      </nav>
      {commandOpen && <CommandPalette open onClose={closeCommand} />}
    </>
  );
}
