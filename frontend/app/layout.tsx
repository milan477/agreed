import type { Metadata } from "next";
import "./globals.css";
import { Assistant } from "@/components/Assistant";

export const metadata: Metadata = {
  title: "Agreed. — better agreements, faster",
  description: "Agentic representation that mathematically aligns diverse stakes into one synthesized agreement.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <Assistant>{children}</Assistant>
      </body>
    </html>
  );
}
