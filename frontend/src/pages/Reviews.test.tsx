import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { RepositoryContext } from "../context/repository-context";
import { api } from "../services/api";
import Reviews from "./Reviews";


vi.mock("../services/api", () => ({
  api: {
    get: vi.fn(),
  },
}));

const apiGet = vi.mocked(api.get);

describe("Reviews", () => {
  beforeEach(() => {
    apiGet.mockReset();
    apiGet.mockResolvedValue({
      data: [
        { id: 11, pr_id: 101, summary: "Authentication boundary review" },
        { id: 12, pr_id: 102, summary: "Database transaction review" },
      ],
    });
  });

  it("loads reviews, filters them, and links to review details", async () => {
    const user = userEvent.setup();
    render(
      <MemoryRouter>
        <RepositoryContext.Provider
          value={{
            repositories: [{ id: 7, full_name: "openai/reviewer" }],
            selectedRepository: { id: 7, full_name: "openai/reviewer" },
            selectedRepositoryId: 7,
            setSelectedRepositoryId: vi.fn(),
            loading: false,
          }}
        >
          <Reviews />
        </RepositoryContext.Provider>
      </MemoryRouter>
    );

    expect(await screen.findByText("2 of 2 reviews")).toBeInTheDocument();
    expect(apiGet).toHaveBeenCalledWith("/repositories/7/reviews");
    expect(screen.getByRole("link", { name: "Review #11" })).toHaveAttribute(
      "href",
      "/reviews/11"
    );

    await user.type(
      screen.getByPlaceholderText("Search review summaries"),
      "database"
    );

    expect(screen.getByText("1 of 2 reviews")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Review #11" })).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Review #12" })).toBeInTheDocument();
  });
});
