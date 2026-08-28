"use client";

import type { Route } from "next";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";

const destinations = [
  { href: "/", label: "Overview", matches: (path: string) => path === "/" },
  {
    href: "/payments/authorize",
    label: "Run payment",
    matches: (path: string) => path === "/payments/authorize" || path === "/demo-checkout",
  },
  {
    href: "/recoveries/verified",
    label: "Live proof",
    matches: (path: string) => path === "/recoveries/verified" || path === "/recovery-story",
  },
  {
    href: "/trace",
    label: "Money trace",
    matches: (path: string) => path === "/trace",
  },
  {
    href: "/judge",
    label: "Scale evidence",
    matches: (path: string) => path === "/judge" || path === "/reliability",
  },
] as const;

const pageNames: Record<string, string> = {
  "/": "Operations overview",
  "/demo-checkout": "Run payment",
  "/judge": "Scale evidence",
  "/payments/authorize": "Run payment",
  "/operations": "Secure operations",
  "/recoveries/verified": "Live recovery proof",
  "/recovery-story": "Recovery story",
  "/reliability": "Scale evidence",
  "/trace": "Money Trace",
};

const fallbackRoutes: Record<string, string> = {
  "/demo-checkout": "/",
  "/judge": "/recoveries/verified",
  "/payments/authorize": "/",
  "/recoveries/verified": "/payments/authorize",
  "/recovery-story": "/recoveries/verified",
  "/reliability": "/recoveries/verified",
  "/trace": "/",
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
          <button aria-label="Go back to the previous page" onClick={goBack} type="button">
            <span aria-hidden="true">←</span>
            Back
          </button>
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
