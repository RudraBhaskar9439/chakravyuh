import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import WalkthroughPage from "./page";

afterEach(cleanup);

describe("platform overview", () => {
  it("provides one linear evidence-first route without credentials", () => {
    render(<WalkthroughPage />);

    expect(
      screen.getByRole("heading", { level: 1, name: /verified recovery/i }),
    ).toBeInTheDocument();
    expect(screen.getAllByRole("link", { name: /₹10 failure/i })[0]).toHaveAttribute(
      "href",
      "/payments/recover-failure?tour=1",
    );
    expect(screen.getByRole("link", { name: /Open Money Trace/i })).toHaveAttribute(
      "href",
      "/trace",
    );
    expect(screen.getByRole("link", { name: /Open reliability report/i })).toHaveAttribute(
      "href",
      "/reliability",
    );
    expect(
      screen.getByText(/Measured proof with explicit operational limits/i),
    ).toBeInTheDocument();
    expect(screen.queryByText(/judge/i)).not.toBeInTheDocument();
    expect(screen.queryByLabelText(/token/i)).not.toBeInTheDocument();
  });
});
