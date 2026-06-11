import "./globals.css";
import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "FanFlow AI — Matchday demand intelligence",
  description: "Privacy-safe World Cup demand intelligence for host-city small businesses.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
