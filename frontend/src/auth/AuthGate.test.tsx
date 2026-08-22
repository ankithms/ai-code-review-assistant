import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AuthGate } from "./AuthGate";
import { api } from "../services/api";


vi.mock("../services/api", () => ({
  api: { get: vi.fn(), post: vi.fn() },
  apiBaseUrl: "/api",
}));

const apiGet = vi.mocked(api.get);

describe("AuthGate", () => {
  beforeEach(() => {
    apiGet.mockReset();
  });

  it("renders protected content for an authenticated session", async () => {
    apiGet.mockResolvedValue({ data: { github_login: "ankithms" } });

    render(<AuthGate><p>Protected dashboard</p></AuthGate>);

    expect(await screen.findByText("Protected dashboard")).toBeInTheDocument();
    expect(apiGet).toHaveBeenCalledWith("/auth/session");
  });

  it("offers GitHub login after a 401 response", async () => {
    apiGet.mockRejectedValue({ response: { status: 401 } });

    render(<AuthGate><p>Protected dashboard</p></AuthGate>);

    const loginLink = await screen.findByRole("link", { name: "Continue with GitHub" });
    expect(loginLink).toHaveAttribute("href", "/api/auth/github/login");
  });
});
