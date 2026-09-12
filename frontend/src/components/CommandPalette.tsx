import {
  GitPullRequest,
  LayoutDashboard,
  Search,
  Sparkles,
  X,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";

type CommandPaletteProps = {
  open: boolean;
  onClose: () => void;
};

const commands = [
  {
    label: "Open dashboard",
    description: "Repository health and review signals",
    path: "/",
    icon: LayoutDashboard,
    keywords: "overview health analytics metrics",
  },
  {
    label: "Browse reviews",
    description: "Search findings and completed reviews",
    path: "/reviews",
    icon: Search,
    keywords: "history findings issues",
  },
  {
    label: "Open pull requests",
    description: "See every reviewed pull request",
    path: "/pull-requests",
    icon: GitPullRequest,
    keywords: "prs github repository",
  },
  {
    label: "Review high-priority findings",
    description: "Jump to reviews with high-severity issues",
    path: "/reviews?filter=high",
    icon: Sparkles,
    keywords: "security critical high priority triage",
  },
];

export default function CommandPalette({ open, onClose }: CommandPaletteProps) {
  const navigate = useNavigate();
  const inputRef = useRef<HTMLInputElement>(null);
  const [query, setQuery] = useState("");
  const [activeIndex, setActiveIndex] = useState(0);
  const closePalette = useCallback(() => {
    setQuery("");
    setActiveIndex(0);
    onClose();
  }, [onClose]);

  const filteredCommands = useMemo(() => {
    const normalized = query.trim().toLowerCase();
    if (!normalized) return commands;

    return commands.filter((command) =>
      `${command.label} ${command.description} ${command.keywords}`
        .toLowerCase()
        .includes(normalized)
    );
  }, [query]);

  useEffect(() => {
    if (!open) return;
    const frame = window.requestAnimationFrame(() => inputRef.current?.focus());
    return () => window.cancelAnimationFrame(frame);
  }, [open]);

  useEffect(() => {
    if (!open) return;

    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        closePalette();
      }
    };

    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [closePalette, open]);

  const runCommand = (path: string) => {
    navigate(path);
    closePalette();
  };

  if (!open) return null;

  return (
    <div className="command-backdrop" onMouseDown={closePalette}>
      <section
        aria-label="Quick navigation"
        aria-modal="true"
        className="command-palette"
        onMouseDown={(event) => event.stopPropagation()}
        role="dialog"
      >
        <div className="command-search">
          <Search aria-hidden="true" size={19} />
          <input
            ref={inputRef}
            aria-activedescendant={filteredCommands[activeIndex] ? `command-option-${activeIndex}` : undefined}
            aria-controls="command-options"
            aria-expanded="true"
            aria-label="Search commands"
            role="combobox"
            placeholder="Where would you like to go?"
            value={query}
            onChange={(event) => {
              setQuery(event.target.value);
              setActiveIndex(0);
            }}
            onKeyDown={(event) => {
              if (event.key === "ArrowDown") {
                event.preventDefault();
                setActiveIndex((index) =>
                  Math.min(index + 1, filteredCommands.length - 1)
                );
              }
              if (event.key === "ArrowUp") {
                event.preventDefault();
                setActiveIndex((index) => Math.max(index - 1, 0));
              }
              if (event.key === "Enter" && filteredCommands[activeIndex]) {
                event.preventDefault();
                runCommand(filteredCommands[activeIndex].path);
              }
            }}
          />
          <button
            aria-label="Close command menu"
            className="icon-button"
            onClick={closePalette}
            type="button"
          >
            <X aria-hidden="true" size={18} />
          </button>
        </div>

        <div className="command-results" id="command-options" role="listbox">
          {filteredCommands.map((command, index) => {
            const Icon = command.icon;
            return (
              <button
                aria-selected={index === activeIndex}
                className={
                  index === activeIndex
                    ? "command-item command-item--active"
                    : "command-item"
                }
                key={command.path}
                id={`command-option-${index}`}
                onClick={() => runCommand(command.path)}
                onMouseEnter={() => setActiveIndex(index)}
                role="option"
                type="button"
              >
                <span className="command-item__icon">
                  <Icon aria-hidden="true" size={18} />
                </span>
                <span>
                  <strong>{command.label}</strong>
                  <small>{command.description}</small>
                </span>
                <kbd>↵</kbd>
              </button>
            );
          })}

          {filteredCommands.length === 0 && (
            <p className="command-empty">No matching destination.</p>
          )}
        </div>

        <footer className="command-footer">
          <span><kbd>↑</kbd><kbd>↓</kbd> navigate</span>
          <span><kbd>↵</kbd> open</span>
          <span><kbd>esc</kbd> close</span>
        </footer>
      </section>
    </div>
  );
}
