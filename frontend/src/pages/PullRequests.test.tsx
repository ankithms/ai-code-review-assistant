import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { RepositoryContext } from "../context/repository-context";
import { api } from "../services/api";
import PullRequests from "./PullRequests";

vi.mock("../services/api", () => ({ api: { get: vi.fn() } }));
const apiGet = vi.mocked(api.get);

function renderPullRequests() {
  return render(
    <MemoryRouter>
      <RepositoryContext.Provider value={{
        repositories: [{ id: 7, full_name: "openai/reviewer" }],
        selectedRepository: { id: 7, full_name: "openai/reviewer" },
        selectedRepositoryId: 7,
        setSelectedRepositoryId: vi.fn(),
        loading: false,
      }}>
        <PullRequests />
      </RepositoryContext.Provider>
    </MemoryRouter>,
  );
}

describe("PullRequests", () => {
  beforeEach(() => {
    apiGet.mockReset();
    apiGet.mockResolvedValue({ data: [{
      id: 101,
      github_pr_id: 12345,
      review_id: 77,
      pull_request_number: 42,
      title: "Harden asynchronous order imports",
      repository: "openai/reviewer",
      author: "octocat",
      source_branch: "feature/order-imports",
      target_branch: "main",
      source_repository: "openai/reviewer",
    }] });
  });

  it("shows source and target branches instead of repeating the repository", async () => {
    renderPullRequests();

    expect(await screen.findByRole("columnheader", { name: "Branches" })).toBeInTheDocument();
    expect(screen.queryByRole("columnheader", { name: "Repository" })).not.toBeInTheDocument();
    expect(screen.getByLabelText("Merging feature/order-imports into main")).toBeInTheDocument();
  });

  it("links a pull request to its latest review in live mode", async () => {
    renderPullRequests();

    expect(await screen.findByRole("link", { name: "Harden asynchronous order imports" }))
      .toHaveAttribute("href", "/reviews/77");
    expect(screen.getByRole("link", { name: "Open review for Harden asynchronous order imports" }))
      .toHaveAttribute("href", "/reviews/77");
  });

  it("leaves a pull request without a review unlinked", async () => {
    apiGet.mockResolvedValueOnce({ data: [{
      id: 102,
      github_pr_id: 12346,
      review_id: null,
      pull_request_number: 43,
      title: "Awaiting first review",
      repository: "openai/reviewer",
      author: "hubot",
      source_branch: "feature/pending",
      target_branch: "main",
      source_repository: "openai/reviewer",
    }] });
    renderPullRequests();

    expect(await screen.findByText("Awaiting first review")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Awaiting first review" })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Open review for Awaiting first review" })).not.toBeInTheDocument();
  });

  it("filters pull requests by branch name", async () => {
    const user = userEvent.setup();
    renderPullRequests();
    const search = await screen.findByRole("searchbox", { name: "Search pull requests" });

    await user.type(search, "order-imports");
    expect(screen.getByText("Harden asynchronous order imports")).toBeInTheDocument();

    await user.clear(search);
    await user.type(search, "missing-branch");
    expect(screen.getByText("No matching pull requests")).toBeInTheDocument();
  });
});
