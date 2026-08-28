import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ProductNavigation } from "./product-navigation";

const back = vi.fn();
const push = vi.fn();
let pathname = "/judge";

vi.mock("next/navigation", () => ({
  usePathname: () => pathname,
  useRouter: () => ({ back, push }),
}));

describe("product navigation", () => {
  afterEach(cleanup);

  beforeEach(() => {
    pathname = "/judge";
    back.mockClear();
    push.mockClear();
    window.sessionStorage.clear();
  });

  it("provides an obvious route out of scale evidence", () => {
    render(<ProductNavigation />);

    expect(screen.getByText("Scale evidence", { selector: "p" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Overview" })).toHaveAttribute("href", "/");
    expect(screen.getByRole("link", { name: "Scale evidence" })).toHaveAttribute(
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

    fireEvent.click(screen.getByRole("link", { name: "Scale evidence" }));
    unmount();
    pathname = "/judge";
    render(<ProductNavigation />);
    fireEvent.click(screen.getByRole("button", { name: "Go back to the previous page" }));

    expect(push).toHaveBeenCalledWith("/recoveries/verified?payment_id=pay_exact");
  });

  it("marks the live proof destination for both proof views", () => {
    pathname = "/recovery-story";
    render(<ProductNavigation />);

    expect(screen.getByRole("link", { name: "Live proof" })).toHaveAttribute(
      "aria-current",
      "page",
    );
  });
});
