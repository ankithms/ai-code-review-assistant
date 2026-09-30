import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import axios from "axios";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { demoAdapter } from "./adapter";

describe("public demo", () => {
  beforeEach(() => {
    window.history.replaceState({}, "", "/demo/");
    window.localStorage.clear();
    window.sessionStorage.clear();
    vi.resetModules();
  });
  afterEach(() => window.history.replaceState({}, "", "/"));

  it("opens without authentication and runs an isolated AI-fix walkthrough without network requests", async () => {
    const network = vi.spyOn(XMLHttpRequest.prototype, "open");
    const { default: App } = await import("../App");
    render(<App />);
    expect(await screen.findByText("AI Code Review Dashboard")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Refresh statuses" })).toBeDisabled();
    await userEvent.click(screen.getByRole("link", { name: "Verified fix" }));
    expect(await screen.findByText("Review #1")).toBeInTheDocument();
    expect(screen.getByText("Sample code diff")).toBeInTheDocument();
    expect(screen.getByText(/Restore the positive-quantity boundary/)).toBeInTheDocument();
    expect(screen.getByText("Fix activity")).toBeInTheDocument();
    expect(screen.getAllByText(/31ca2c9/).length).toBeGreaterThan(0);
    expect(document.querySelectorAll(".demo-diff__line--removed").length).toBeGreaterThan(0);
    await userEvent.click(screen.getByRole("link", { name: "See the follow-up review after the fix →" }));
    expect(await screen.findByText("Review #2")).toBeInTheDocument();
    expect(screen.getByText("This review did not report any issues.")).toBeInTheDocument();
    expect(document.querySelectorAll(".demo-diff__line--added").length).toBeGreaterThan(0);
    await userEvent.click(screen.getByRole("link", { name: "Pull Requests" }));
    await userEvent.click(await screen.findByRole("link", { name: "Reject invalid order quantities" }));
    expect(await screen.findByText("Review #1")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("link", { name: "Try AI fix" }));
    expect(await screen.findByText("Review #4")).toBeInTheDocument();
    expect(screen.getByText("5 Issues")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Select eligible" }));
    expect(screen.getByText("5 selected")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Generate Fixes" }));
    expect(await screen.findByText("Fixes generated.")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Validate & Preview" }));
    expect(await screen.findByText("Valid preview")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Apply Demo Fix" }));
    const applyButtons = screen.getAllByRole("button", { name: "Apply Demo Fix" });
    await userEvent.click(applyButtons[applyButtons.length - 1]);
    expect((await screen.findAllByText("All issues resolved")).length).toBeGreaterThan(0);
    expect(network).not.toHaveBeenCalled();
  });

  it("supports direct links to the clean review", async () => {
    window.history.replaceState({}, "", "/demo/reviews/3");
    const { default: App } = await import("../App");
    render(<App />);
    expect(await screen.findByText("This review did not report any issues.")).toBeInTheDocument();
  });

  it("keeps demo mutations local and rejects unknown URLs without a live API fallback", async () => {
    const client = axios.create({ adapter: demoAdapter });
    await client.patch("/repositories/1/reviews/issues/507/status", { status: "IGNORED" });
    const review = await client.get("/repositories/1/reviews/5");
    expect(review.data.issues.find((finding: { id: number }) => finding.id === 507).status).toBe("IGNORED");
    await expect(client.post("/repositories/1/unknown", {}))
      .rejects.toMatchObject({ response: { status: 404 } });
    await expect(client.get("/auth/session")).rejects.toMatchObject({ response: { status: 404 } });
    const first = await client.get("/repositories");
    first.data[0].full_name = "modified";
    expect((await client.get("/repositories")).data[0].full_name).toBe("demo/order-service");
  });
});
