import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import JudgePage from "./page";
import { proofRoots } from "./proof-data";

afterEach(cleanup);

describe("judge evidence room", () => {
  it("separates evidence sources and exposes no money-action control", () => {
    render(<JudgePage />);

    expect(
      screen.getByRole("heading", { level: 1, name: /Follow the money/i }),
    ).toBeInTheDocument();
    expect(screen.getByText("Held-out synthetic")).toBeInTheDocument();
    expect(screen.getByText("Live AI")).toBeInTheDocument();
    expect(screen.getByText("Provider transaction")).toBeInTheDocument();
    expect(screen.getByText("Local scale")).toBeInTheDocument();
    expect(screen.getByText(/action endpoints disconnected/i)).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /execute|approve|capture/i }),
    ).not.toBeInTheDocument();
    expect(screen.getByText(proofRoots.tournament)).toBeInTheDocument();
  });

  it("moves through funnel, evidence, chaos, and exception proofs", () => {
    render(<JudgePage />);

    fireEvent.click(screen.getByRole("button", { name: /Recovery funnel/i }));
    expect(screen.getByText("10,005 journeys. 402 confirmed recoveries.")).toBeInTheDocument();
    expect(screen.getByText("Unconfirmed recoveries credited")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /Evidence mesh/i }));
    expect(screen.getByRole("img", { name: /connected money evidence mesh/i })).toBeInTheDocument();
    expect(screen.getByText("The model can explain. It cannot move money.")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /^04 Chaos$/i }));
    expect(screen.getByText("Crash after mutation")).toBeInTheDocument();
    expect(screen.getAllByText("Passed")).toHaveLength(9);
    expect(screen.getByText(proofRoots.fullPipeline)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /Exceptions/i }));
    expect(screen.getByText("Invalid structured response")).toBeInTheDocument();
    expect(screen.getByText(/Safe abstention beats fabricated certainty/i)).toBeInTheDocument();
  });
});
