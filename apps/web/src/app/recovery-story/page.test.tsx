import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import RecoveryStoryPage from "./page";
import { proofLedger } from "./proof-data";

afterEach(cleanup);

describe("verified recovery story", () => {
  it("presents the completed provider recovery without money-action controls", () => {
    render(<RecoveryStoryPage />);

    expect(
      screen.getByRole("heading", { level: 1, name: /A payment got stuck/i }),
    ).toBeInTheDocument();
    expect(screen.getByText("Read-only record")).toBeInTheDocument();
    expect(screen.getByText("Razorpay Test Mode")).toBeInTheDocument();
    expect(screen.getByText("₹10", { selector: "dd" })).toBeInTheDocument();
    expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /approve|execute|capture/i }),
    ).not.toBeInTheDocument();
    expect(screen.getByText(proofLedger[6].hash)).toBeInTheDocument();
  });

  it("lets a judge inspect every recovery moment", () => {
    render(<RecoveryStoryPage />);

    fireEvent.click(screen.getByRole("button", { name: /03 Explain/i }));
    expect(screen.getByText(/AI explained the graph/i)).toBeInTheDocument();
    expect(screen.getByText("2,119 tokens · $0.000940")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /05 Recover/i }));
    expect(screen.getByText(/One mutation. Zero duplicates/i)).toBeInTheDocument();
    expect(screen.getByText("Provider-confirmed recovery")).toBeInTheDocument();
  });
});
