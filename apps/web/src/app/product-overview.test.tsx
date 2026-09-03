import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { ProductOverview } from "./product-overview";

afterEach(cleanup);

describe("product overview", () => {
  it("presents one primary recovery action and clear operational destinations", () => {
    render(<ProductOverview />);

    expect(
      screen.getByRole("heading", { name: /Recover revenue.*Keep every action under control/i }),
    ).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Start a recovery/i })).toHaveAttribute(
      "href",
      "/payments/authorize",
    );
    expect(screen.getByRole("link", { name: /View verified transaction/i })).toHaveAttribute(
      "href",
      "/recoveries/verified",
    );
    expect(screen.getByRole("link", { name: /Recover a failed payment/i })).toHaveAttribute(
      "href",
      "/payments/recover-failure",
    );
    expect(screen.getByRole("link", { name: /Search transactions/i })).toHaveAttribute(
      "href",
      "/trace",
    );
    expect(screen.queryByText(/judge/i)).not.toBeInTheDocument();
    expect(screen.queryByLabelText(/operator access token/i)).not.toBeInTheDocument();
  });
});
