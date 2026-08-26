import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, expect, test, vi } from "vitest";
import { request } from "../../api/client";
import { PatchSuggestionsPanel } from "./PatchSuggestionsPanel";
vi.mock("../../api/client", () => ({ request: vi.fn() }));
const api = vi.mocked(request);
beforeEach(() => api.mockReset());
test("shows empty state and permits generation for developers", async () => {
  api.mockResolvedValueOnce({ items: [] });
  api.mockResolvedValueOnce({});
  render(<PatchSuggestionsPanel analysisId="a1" />);
  expect(
    await screen.findByText("No patch suggestion exists."),
  ).toBeInTheDocument();
  fireEvent.click(
    screen.getByRole("button", { name: "Generate patch suggestion" }),
  );
  expect(api).toHaveBeenCalledWith("/analyses/a1/generate-patch", {
    method: "POST",
  });
});
test("renders rejected validation without generation for viewers", async () => {
  api.mockResolvedValue({
    items: [
      {
        id: "p1",
        status: "REJECTED_BY_VALIDATION",
        provider: "GROQ",
        model: "test",
        unifiedDiff: "",
        explanation: "Rejected",
        confidence: 0.5,
        riskLevel: "HIGH",
        affectedFiles: [],
        validationErrors: ["Forbidden file path"],
      },
    ],
  });
  render(<PatchSuggestionsPanel analysisId="a2" role="VIEWER" />);
  expect(await screen.findByText("REJECTED_BY_VALIDATION")).toBeInTheDocument();
  expect(screen.getByText(/Forbidden file path/)).toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: "Generate patch suggestion" }),
  ).not.toBeInTheDocument();
});
