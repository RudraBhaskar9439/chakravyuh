"use client";

import type { Route } from "next";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";

const destinations = [
  { href: "/", label: "Overview", matches: (path: string) => path === "/" },
  {
    href: "/payments/authorize",
    label: "Recover",
    matches: (path: string) =>
      path === "/payments/authorize" ||
      path === "/payments/recover-failure" ||
      path === "/demo-checkout",
  },
  {
    href: "/recoveries/verified",
    label: "Verify",
    matches: (path: string) => path === "/recoveries/verified" || path === "/recovery-story",
  },
  {
    href: "/trace",
    label: "Trace",
    matches: (path: string) => path === "/trace",
  },
  {
    href: "/reliability",
    label: "Reliability",
    matches: (path: string) => path === "/judge" || path === "/reliability",
  },
] as const;

const pageNames: Record<string, string> = {
  "/": "Control center",
  "/demo-checkout": "Payment recovery",
  "/judge": "Reliability",
  "/payments/authorize": "Authorization recovery",
  "/payments/recover-failure": "Failure recovery",
  "/operations": "Secure operations",
  "/recoveries/verified": "Verification ledger",
  "/recovery-story": "Recovery record",
  "/reliability": "Reliability",
  "/trace": "Money Trace",
  "/walkthrough": "Platform overview",
};

const fallbackRoutes: Record<string, string> = {
  "/demo-checkout": "/",
  "/judge": "/reliability",
  "/payments/authorize": "/",
  "/payments/recover-failure": "/",
  "/recoveries/verified": "/payments/authorize",
  "/recovery-story": "/recoveries/verified",
  "/reliability": "/recoveries/verified",
  "/trace": "/",
  "/walkthrough": "/",
};

const returnKey = (destination: string) => `chakravyuh:return:${destination}`;

export function ProductNavigation() {
  const pathname = usePathname();
  const router = useRouter();
  const currentPage = pageNames[pathname] ?? "Chakravyuh";

  function goBack() {
    const savedPath = window.sessionStorage.getItem(returnKey(pathname));
    if (savedPath?.startsWith("/") && !savedPath.startsWith("//")) {
      window.sessionStorage.removeItem(returnKey(pathname));
      router.push(savedPath as Route);
      return;
    }
    router.push((fallbackRoutes[pathname] ?? "/") as Route);
  }

  function rememberReturn(destination: string) {
    if (destination === pathname) return;
    window.sessionStorage.setItem(
      returnKey(destination),
      `${window.location.pathname}${window.location.search}`,
    );
  }

  return (
    <header className="productNavShell">
      <div className="productNavInner">
        <div className="productNavContext">
          {pathname !== "/" ? (
            <button aria-label="Go back to the previous page" onClick={goBack} type="button">
              <span aria-hidden="true">←</span>
              Back
            </button>
          ) : null}
          <Link className="productNavBrand" href="/" aria-label="Chakravyuh overview">
            <span aria-hidden="true">च</span>
            <strong>Chakravyuh</strong>
          </Link>
          <span className="productNavDivider" aria-hidden="true" />
          <p aria-live="polite">{currentPage}</p>
        </div>

        <nav aria-label="Primary product navigation">
          {destinations.map((destination) => {
            const active = destination.matches(pathname);
            return (
              <Link
                aria-current={active ? "page" : undefined}
                className={active ? "active" : undefined}
                href={destination.href as Route}
                key={destination.href}
                onClick={() => rememberReturn(destination.href)}
              >
                {destination.label}
              </Link>
            );
          })}
        </nav>

        <div className="productNavMode">
          <span aria-hidden="true" />
          Test Mode
        </div>
      </div>
    </header>
  );
}
