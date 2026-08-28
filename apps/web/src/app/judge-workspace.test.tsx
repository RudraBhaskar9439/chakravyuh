import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { JudgeWorkspace } from "./judge-workspace";

afterEach(cleanup);

describe("judge workspace", () => {
  it("offers one tokenless guided journey and direct evidence routes", () => {
    render(<JudgeWorkspace />);

    expect(screen.getByRole("heading", { name: /repair itself/i })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Start verified recovery/i })).toHaveAttribute(
      "href",
      "/payments/authorize",
    );
    expect(screen.getByRole("link", { name: /Find an existing transaction/i })).toHaveAttribute(
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
