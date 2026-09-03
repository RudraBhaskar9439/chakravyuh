import type { Metadata } from "next";
import type { ReactNode } from "react";

import "./globals.css";
import { ProductNavigation } from "./product-navigation";

export const metadata: Metadata = {
  title: "Chakravyuh · Payment Recovery Control",
  description: "Detect, govern, execute, and verify payment recovery with evidence-first controls",
};

type RootLayoutProps = Readonly<{
  children: ReactNode;
}>;

export default function RootLayout({ children }: RootLayoutProps) {
  return (
    <html lang="en">
      <body>
        <ProductNavigation />
        {children}
      </body>
    </html>
  );
}
