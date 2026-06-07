import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "agreed — better agreements, faster",
  description: "AI agents represent humans in negotiation and reach optimal, transparent agreements.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
