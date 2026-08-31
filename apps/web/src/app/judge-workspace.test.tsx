import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { JudgeWorkspace } from "./judge-workspace";

afterEach(cleanup);

describe("judge workspace", () => {
  it("offers two tokenless guided journeys and direct evidence routes", () => {
    render(<JudgeWorkspace />);

    expect(screen.getByRole("heading", { name: /repair itself/i })).toBeInTheDocument();
    expect(screen.getAllByRole("link", { name: /judge walkthrough/i })[0]).toHaveAttribute(
      "href",
      "/walkthrough",
    );
    expect(screen.getByRole("link", { name: /Recover an uncaptured payment/i })).toHaveAttribute(
      "href",
      "/payments/authorize",
    );
    expect(screen.getByRole("link", { name: /^Recover a failed payment$/i })).toHaveAttribute(
      "href",
      "/payments/recover-failure",
    );
    expect(screen.getByRole("link", { name: /Money TraceResolve/i })).toHaveAttribute(
      "href",
      "/trace",
    );
    expect(screen.queryByLabelText(/operator access token/i)).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Secure operator console/i })).toHaveAttribute(
      "href",
      "/operations",
    );
  });
});
