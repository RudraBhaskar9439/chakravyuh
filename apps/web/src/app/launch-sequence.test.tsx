import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { LaunchSequence } from "./launch-sequence";

afterEach(() => {
  cleanup();
  vi.useRealTimers();
  window.sessionStorage.clear();
});

describe("launch sequence", () => {
  it("can be skipped and is remembered for the browser session", () => {
    vi.useFakeTimers();
    render(<LaunchSequence />);

    expect(screen.getByLabelText("Chakravyuh introduction")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Skip intro" }));
    act(() => vi.advanceTimersByTime(450));

    expect(screen.queryByLabelText("Chakravyuh introduction")).not.toBeInTheDocument();
    expect(window.sessionStorage.getItem("chakravyuh:launch-sequence:v1")).toBe("seen");
  });

  it("does not replay after it has been seen", () => {
    window.sessionStorage.setItem("chakravyuh:launch-sequence:v1", "seen");
    render(<LaunchSequence />);

    expect(screen.queryByLabelText("Chakravyuh introduction")).not.toBeInTheDocument();
  });

  it("hands control to the homepage after the sequence completes", () => {
    vi.useFakeTimers();
    render(<LaunchSequence />);

    act(() => vi.advanceTimersByTime(3_800));

    expect(screen.queryByLabelText("Chakravyuh introduction")).not.toBeInTheDocument();
    expect(window.sessionStorage.getItem("chakravyuh:launch-sequence:v1")).toBe("seen");
  });
});
