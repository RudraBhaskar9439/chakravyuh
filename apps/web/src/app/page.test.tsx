import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import Home from "./page";

describe("Home", () => {
  it("states the product boundary and durable-normalization status", () => {
    render(<Home />);

    expect(screen.getByRole("heading", { level: 1, name: "Chakravyuh" })).toBeInTheDocument();
    expect(screen.getByText("Intake and normalization operational")).toBeInTheDocument();
    expect(screen.getByText("AI proposes; deterministic controls authorize")).toBeInTheDocument();
  });
});
