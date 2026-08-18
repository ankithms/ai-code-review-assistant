import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { api } from "../services/api";
import { RepositoryProvider } from "./RepositoryContext";
import { useRepository } from "./useRepository";


vi.mock("../services/api", () => ({
  api: {
    get: vi.fn(),
  },
}));

const apiGet = vi.mocked(api.get);

function RepositoryConsumer() {
  const {
    repositories,
    selectedRepository,
    setSelectedRepositoryId,
    loading,
  } = useRepository();

  if (loading) {
    return <p>Loading</p>;
  }

  return (
    <div>
      <p>Selected: {selectedRepository?.full_name ?? "none"}</p>
      {repositories.map((repository) => (
        <button
          key={repository.id}
          type="button"
          onClick={() => setSelectedRepositoryId(repository.id)}
        >
          Choose {repository.full_name}
        </button>
      ))}
    </div>
  );
}

describe("RepositoryProvider", () => {
  beforeEach(() => {
    window.localStorage.clear();
    apiGet.mockReset();
    apiGet.mockResolvedValue({
      data: [
        { id: 1, full_name: "openai/alpha" },
        { id: 2, full_name: "openai/beta" },
      ],
    });
  });

  it("restores the stored repository selection", async () => {
    window.localStorage.setItem("selectedRepositoryId", "2");

    render(
      <RepositoryProvider>
        <RepositoryConsumer />
      </RepositoryProvider>
    );

    expect(await screen.findByText("Selected: openai/beta")).toBeInTheDocument();
    expect(apiGet).toHaveBeenCalledWith("/repositories");
  });

  it("selects the first repository and persists later changes", async () => {
    const user = userEvent.setup();

    render(
      <RepositoryProvider>
        <RepositoryConsumer />
      </RepositoryProvider>
    );

    expect(await screen.findByText("Selected: openai/alpha")).toBeInTheDocument();
    expect(window.localStorage.getItem("selectedRepositoryId")).toBe("1");

    await user.click(screen.getByRole("button", { name: "Choose openai/beta" }));

    await waitFor(() => {
      expect(screen.getByText("Selected: openai/beta")).toBeInTheDocument();
      expect(window.localStorage.getItem("selectedRepositoryId")).toBe("2");
    });
  });
});

