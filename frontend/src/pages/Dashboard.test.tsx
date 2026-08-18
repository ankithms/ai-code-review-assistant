import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { RepositoryContext } from "../context/repository-context";
import { api } from "../services/api";
import Dashboard from "./Dashboard";


vi.mock("../services/api", () => ({
  api: {
    get: vi.fn(),
    post: vi.fn(),
  },
}));

const apiGet = vi.mocked(api.get);
const apiPost = vi.mocked(api.post);

const analytics = {
  total_ai_reviews: 4,
  total_reviews: 4,
  total_pull_requests: 3,
  total_issues: 7,
  high_severity: 2,
  medium_severity: 3,
  low_severity: 2,
  open_issues: 5,
  resolved_issues: 1,
  ignored_issues: 1,
  bug_issues: 3,
  security_issues: 2,
  performance_issues: 1,
  readability_issues: 1,
  edge_case_issues: 0,
  top_problematic_files: [
    { file: "src/auth.py", total_issues: 3 },
  ],
  average_issues_per_pull_request: 2.33,
  average_review_processing_time_seconds: 12.5,
};

function renderDashboard() {
  return render(
    <RepositoryContext.Provider
      value={{
        repositories: [{ id: 7, full_name: "openai/reviewer" }],
        selectedRepository: { id: 7, full_name: "openai/reviewer" },
        selectedRepositoryId: 7,
        setSelectedRepositoryId: vi.fn(),
        loading: false,
      }}
    >
      <Dashboard />
    </RepositoryContext.Provider>
  );
}

describe("Dashboard", () => {
  beforeEach(() => {
    apiGet.mockReset();
    apiPost.mockReset();
    apiGet.mockResolvedValue({ data: analytics });
  });

  it("loads and renders repository analytics", async () => {
    renderDashboard();

    expect(screen.getByText("Loading analytics...")).toBeInTheDocument();
    expect(await screen.findByText("openai/reviewer")).toBeInTheDocument();
    expect(apiGet).toHaveBeenCalledWith("/repositories/7/analytics");

    const reviewCard = screen.getByText("AI Reviews").closest<HTMLElement>(".stat-card");
    expect(reviewCard).not.toBeNull();
    expect(within(reviewCard!).getByText("4")).toBeInTheDocument();
    expect(screen.getByText("12.5s")).toBeInTheDocument();
    expect(screen.getByText("src/auth.py")).toBeInTheDocument();
  });

  it("refreshes issue statuses and renders the updated analytics", async () => {
    const user = userEvent.setup();
    apiPost.mockResolvedValue({
      data: {
        ...analytics,
        open_issues: 3,
        resolved_issues: 3,
      },
    });
    renderDashboard();
    await screen.findByText("openai/reviewer");

    await user.click(screen.getByRole("button", { name: "Refresh statuses" }));

    expect(apiPost).toHaveBeenCalledWith("/repositories/7/analytics/sync");
    expect(await screen.findByText("Updated")).toBeInTheDocument();
    const openIssuesCard = screen
      .getByText("Open Issues")
      .closest<HTMLElement>(".stat-card");
    expect(within(openIssuesCard!).getByText("3")).toBeInTheDocument();
  });
});
