import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { RepositoryContext } from "../context/repository-context";
import { api } from "../services/api";
import ReviewDetail from "./ReviewDetail";


vi.mock("../services/api", () => ({
  api: {
    get: vi.fn(),
    post: vi.fn(),
    patch: vi.fn(),
  },
}));

const apiGet = vi.mocked(api.get);
const apiPost = vi.mocked(api.post);

const review = {
  id: 42,
  pr_id: 101,
  summary: "One security issue requires attention.",
  issues: [
    {
      id: 5,
      severity: "high",
      category: "security",
      file: "src/auth.py",
      comment: "User input reaches a SQL query.",
      status: "OPEN",
      fix_status: "NO_FIX",
      eligible_for_fix: true,
    },
  ],
  fix_commits: [],
};

const completedFixCommit = {
  id: 9,
  status: "REVIEWED",
  validation_status: "PASSED",
  applied_issue_ids: [5],
  requested_issue_count: 1,
  valid_issue_count: 1,
  skipped_issue_count: 0,
  resolved_issue_count: 1,
  remaining_issue_count: 0,
  moved_issue_count: 0,
  new_issue_count: 0,
  failed_issue_count: 0,
  issues: [],
  new_issues: [],
  verification_status: "COMPLETED",
  created_at: "2026-08-18T00:00:00Z",
  updated_at: "2026-08-18T00:00:00Z",
};

const skippedFixAttempt = {
  ...completedFixCommit,
  id: 10,
  status: "VALIDATING",
  validation_status: "FAILED",
  valid_issue_count: 0,
  skipped_issue_count: 1,
  issues: [{
    issue_id: 5,
    status: "SKIPPED",
    generated: false,
    validated: false,
    committed: false,
    original_file: "src/auth.py",
    original_line: 10,
    skip_reason: "does not have a generated fix",
  }],
};

describe("ReviewDetail", () => {
  beforeEach(() => {
    apiGet.mockReset();
    apiPost.mockReset();
    apiGet.mockImplementation((url) => {
      if (String(url).includes("/fix-commits/")) {
        return Promise.resolve({ data: completedFixCommit });
      }
      return Promise.resolve({ data: review });
    });
    apiPost.mockResolvedValue({
      data: {
        status: "GENERATING",
        fix_commit_id: 9,
      },
    });
  });

  it("loads a review and requests fixes for all eligible findings", async () => {
    const user = userEvent.setup();
    render(
      <MemoryRouter initialEntries={["/reviews/42"]}>
        <RepositoryContext.Provider
          value={{
            repositories: [{ id: 7, full_name: "openai/reviewer" }],
            selectedRepository: { id: 7, full_name: "openai/reviewer" },
            selectedRepositoryId: 7,
            setSelectedRepositoryId: vi.fn(),
            loading: false,
          }}
        >
          <Routes>
            <Route path="/reviews/:id" element={<ReviewDetail />} />
          </Routes>
        </RepositoryContext.Provider>
      </MemoryRouter>
    );

    expect(await screen.findByText("Review #42")).toBeInTheDocument();
    expect(screen.getByText("User input reaches a SQL query.")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Generate Fixes" }));

    expect(apiPost).toHaveBeenCalledWith(
      "/repositories/7/reviews/42/fixes/generate",
      {
        issue_ids: [5],
        retry: false,
      }
    );
    expect(await screen.findByText("Fixes generated.")).toBeInTheDocument();
  });

  it("shows an unsuccessful request as a compact activity event", async () => {
    apiGet.mockResolvedValue({
      data: { ...review, fix_commits: [skippedFixAttempt] },
    });

    render(
      <MemoryRouter initialEntries={["/reviews/42"]}>
        <RepositoryContext.Provider
          value={{
            repositories: [{ id: 7, full_name: "openai/reviewer" }],
            selectedRepository: { id: 7, full_name: "openai/reviewer" },
            selectedRepositoryId: 7,
            setSelectedRepositoryId: vi.fn(),
            loading: false,
          }}
        >
          <Routes><Route path="/reviews/:id" element={<ReviewDetail />} /></Routes>
        </RepositoryContext.Provider>
      </MemoryRouter>
    );

    expect(await screen.findByText("Fix activity")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Failed" })).toBeInTheDocument();
    expect(screen.getByText("does not have a generated fix")).toBeInTheDocument();
    expect(screen.getByText("Issue #5")).toBeInTheDocument();
    expect(screen.getByText("src/auth.py:10")).toBeInTheDocument();
    expect(screen.getByText("Fixes ready")).toBeInTheDocument();
    expect(screen.getByText("View details")).toBeInTheDocument();
    expect(screen.queryByText("Still open")).not.toBeInTheDocument();
    expect(screen.queryByText("Requested / committed")).not.toBeInTheDocument();
  });
});
