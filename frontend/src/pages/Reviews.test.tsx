import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { RepositoryContext } from "../context/repository-context";
import { api } from "../services/api";
import Reviews from "./Reviews";

vi.mock("../services/api", () => ({ api: { get: vi.fn() } }));
const apiGet = vi.mocked(api.get);

const initialRun = {
  review_id: 11, job_id: 21, commit_sha: "abc123456", run_type: "Initial review",
  status: "COMPLETED", result: "2 new findings", finding_count: 2, resolved_count: 0,
  created_at: "2026-09-14T08:00:00Z",
};
const incrementalRun = {
  review_id: 12, job_id: 22, commit_sha: "def567890", run_type: "Incremental review",
  status: "COMPLETED", result: "No new findings", finding_count: 0, resolved_count: 0,
  created_at: "2026-09-15T08:00:00Z",
};

function renderReviews() {
  return render(
    <MemoryRouter>
      <RepositoryContext.Provider value={{
        repositories: [{ id: 7, full_name: "openai/reviewer" }],
        selectedRepository: { id: 7, full_name: "openai/reviewer" },
        selectedRepositoryId: 7, setSelectedRepositoryId: vi.fn(), loading: false,
      }}>
        <Reviews />
      </RepositoryContext.Provider>
    </MemoryRouter>
  );
}

describe("Reviews", () => {
  beforeEach(() => {
    apiGet.mockReset();
    apiGet.mockResolvedValue({ data: [{
      pr_id: 101, repository: "openai/reviewer", pr_number: 42,
      title: "Harden asynchronous order imports", author: "octocat",
      latest_reviewed_commit_sha: "def567890", latest_review_id: 12,
      latest_review_time: "2026-09-15T08:00:00Z", open_findings: 1,
      resolved_findings: 1, ignored_findings: 1, highest_open_severity: "high",
      latest_run: incrementalRun, review_history: [incrementalRun, initialRun],
    }] });
  });

  it("renders one PR card and keeps zero-new updates distinct from aggregate health", async () => {
    renderReviews();

    expect(await screen.findByText("1 of 1 pull requests")).toBeInTheDocument();
    expect(apiGet).toHaveBeenCalledWith("/repositories/7/reviews/overview");
    expect(screen.getAllByText("Harden asynchronous order imports")).toHaveLength(1);
    expect(screen.getByText("Open findings remain")).toBeInTheDocument();
    expect(screen.getByText("1 open", { exact: false })).toBeInTheDocument();
    expect(screen.getByText("No new findings")).toBeInTheDocument();
    expect(screen.getByText(/earlier findings remain open/i)).toBeInTheDocument();
  });

  it("expands the complete audit trail and links each snapshot to its detail", async () => {
    const user = userEvent.setup();
    renderReviews();
    const toggle = await screen.findByRole("button", { name: /review history 2 runs/i });

    expect(toggle).toHaveAttribute("aria-expanded", "false");
    await user.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "true");

    const history = screen.getByText(/commit-specific audit trail/i).parentElement!;
    expect(within(history).getByText("Initial review")).toBeInTheDocument();
    expect(within(history).getByText("Incremental review")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /open initial review for commit abc1234/i })).toHaveAttribute("href", "/reviews/11");
    expect(screen.getByRole("link", { name: /open incremental review for commit def5678/i })).toHaveAttribute("href", "/reviews/12");
  });

  it("filters PR cards using aggregate current health", async () => {
    const user = userEvent.setup();
    renderReviews();
    await screen.findByText("1 of 1 pull requests");
    await user.click(screen.getByRole("button", { name: "Clean" }));
    expect(screen.getByText("0 of 1 pull requests")).toBeInTheDocument();
    expect(screen.getByText("No matching pull requests")).toBeInTheDocument();
  });
});
