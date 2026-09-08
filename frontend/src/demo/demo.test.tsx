import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import axios from "axios";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { demoAdapter } from "./adapter";

describe("public demo", () => {
  beforeEach(() => {
    window.history.replaceState({}, "", "/demo/");
    window.localStorage.clear();
    vi.resetModules();
  });
  afterEach(() => window.history.replaceState({}, "", "/"));

  it("opens without authentication and lets visitors inspect findings without network requests", async () => {
    const network = vi.spyOn(XMLHttpRequest.prototype, "open");
    const { default: App } = await import("../App");
    render(<App />);
    expect(await screen.findByText("AI Code Review Dashboard")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Refresh statuses" })).toBeDisabled();
    await userEvent.click(screen.getByRole("link", { name: "Explore a sample review →" }));
    expect(await screen.findByText("Review #1")).toBeInTheDocument();
    expect(screen.getByText("Sample code diff")).toBeInTheDocument();
    expect(screen.getByText(/Handle the empty collection/)).toBeInTheDocument();
    for (const name of ["Generate Fixes", "Preview", "Commit AI Fix", "OPEN", "RESOLVED", "IGNORED"]) {
      expect(screen.getByRole("button", { name })).toBeDisabled();
    }
    await userEvent.click(screen.getByRole("link", { name: "See the follow-up review after the fix →" }));
    expect(await screen.findByText("Review #2")).toBeInTheDocument();
    expect(screen.getByText("This review did not report any issues.")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("link", { name: "Pull Requests" }));
    await userEvent.click(await screen.findByRole("link", { name: "Calculate average cart price" }));
    expect(await screen.findByText("Review #1")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("link", { name: "See unresolved findings →" }));
    expect(await screen.findByText("Review #4")).toBeInTheDocument();
    expect(screen.getByText("2 Issues")).toBeInTheDocument();
    expect(screen.getByText(/When requested quantity exactly matches stock/)).toBeInTheDocument();
    expect(screen.getByText(/The order lookup no longer checks/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Commit AI Fix" })).toBeDisabled();
    expect(network).not.toHaveBeenCalled();
  });

  it("supports direct links to the clean review", async () => {
    window.history.replaceState({}, "", "/demo/reviews/3");
    const { default: App } = await import("../App");
    render(<App />);
    expect(await screen.findByText("This review did not report any issues.")).toBeInTheDocument();
  });

  it("rejects writes and unknown URLs without falling back to the live API", async () => {
    const client = axios.create({ adapter: demoAdapter });
    for (const method of ["post", "patch", "put", "delete"]) {
      await expect(client.request({ method, url: "/repositories/1/reviews/1/fixes/generate" }))
        .rejects.toMatchObject({ response: { status: 403 } });
    }
    await expect(client.get("/auth/session")).rejects.toMatchObject({ response: { status: 404 } });
    const first = await client.get("/repositories");
    first.data[0].full_name = "modified";
    expect((await client.get("/repositories")).data[0].full_name).toBe("demo/shop-api");
  });
});
