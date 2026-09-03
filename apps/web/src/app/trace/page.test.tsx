import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import MoneyTracePage from "./page";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("Money Trace", () => {
  it("rejects identifiers that cannot belong to the money graph", async () => {
    render(<MoneyTracePage />);
    fireEvent.change(screen.getByLabelText(/Payment, order/i), { target: { value: "hello" } });
    fireEvent.click(screen.getByRole("button", { name: "Trace money" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/Enter a pay_/i);
  });

  it("resolves a content-addressed scale report", async () => {
    const hash = "a".repeat(64);
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        json: async () => ({ reportSha256: hash, proofRoots: {} }),
      }),
    );
    render(<MoneyTracePage />);
    fireEvent.change(screen.getByLabelText(/Payment, order/i), { target: { value: hash } });
    fireEvent.click(screen.getByRole("button", { name: "Trace money" }));
    await waitFor(() => expect(screen.getByText("Scale evidence report")).toBeInTheDocument());
    expect(screen.getByRole("link", { name: /Open reliability report/i })).toHaveAttribute(
      "href",
      "/reliability",
    );
  });
});
