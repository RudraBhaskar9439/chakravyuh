import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ProductNavigation } from "./product-navigation";

const back = vi.fn();
const push = vi.fn();
let pathname = "/reliability";

vi.mock("next/navigation", () => ({
  usePathname: () => pathname,
  useRouter: () => ({ back, push }),
}));

describe("product navigation", () => {
  afterEach(cleanup);

  beforeEach(() => {
    pathname = "/reliability";
    back.mockClear();
    push.mockClear();
    window.sessionStorage.clear();
  });

  it("provides an obvious route out of scale evidence", () => {
    render(<ProductNavigation />);

    expect(screen.getByText("Reliability", { selector: "p" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Overview" })).toHaveAttribute("href", "/");
    expect(screen.getByRole("link", { name: "Reliability" })).toHaveAttribute(
      "aria-current",
      "page",
    );

    fireEvent.click(screen.getByRole("button", { name: "Go back to the previous page" }));
    expect(push).toHaveBeenCalledWith("/recoveries/verified");
  });

  it("returns to the exact payment proof that opened scale evidence", () => {
    pathname = "/recoveries/verified";
    window.history.replaceState({}, "", "/recoveries/verified?payment_id=pay_exact");
    const { unmount } = render(<ProductNavigation />);

    fireEvent.click(screen.getByRole("link", { name: "Reliability" }), { ctrlKey: true });
    unmount();
    pathname = "/reliability";
    render(<ProductNavigation />);
    fireEvent.click(screen.getByRole("button", { name: "Go back to the previous page" }));

    expect(push).toHaveBeenCalledWith("/recoveries/verified?payment_id=pay_exact");
  });

  it("marks the live proof destination for both proof views", () => {
    pathname = "/recovery-story";
    render(<ProductNavigation />);

    expect(screen.getByRole("link", { name: "Verify" })).toHaveAttribute("aria-current", "page");
  });
});
