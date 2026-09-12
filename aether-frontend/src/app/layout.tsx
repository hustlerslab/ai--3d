import type { Metadata } from "next";
import { Inter, Playfair_Display } from "next/font/google";
import Link from "next/link";

import "./globals.css";

const playfair = Playfair_Display({
  subsets: ["latin"],
  weight: ["400", "700"],
  variable: "--font-display",
  display: "swap",
});

const inter = Inter({
  subsets: ["latin"],
  weight: ["400", "500", "600"],
  variable: "--font-body",
  display: "swap",
});

export const metadata: Metadata = {
  title: {
    default: "Allure Walkthrough",
    template: "%s · Allure Walkthrough",
  },
  description:
    "From an idea to a space you can walk through — moodboard, 3D generation, and an interactive walkthrough on the Aether engine.",
};

const NAV = [
  { href: "/", label: "Studio" },
  { href: "/3d", label: "3D viewer" },
  { href: "/cinematic", label: "Cinematic film" },
];

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en-IN" className={`${playfair.variable} ${inter.variable}`}>
      <body>
        <header className="border-b bg-surface-raised">
          <div className="mx-auto flex max-w-7xl items-center justify-between px-6 py-3">
            <Link href="/" className="flex items-baseline gap-2">
              <span className="wordmark text-sm text-ink-soft">Allure</span>
              <span className="caption text-ink-muted">Walkthrough</span>
            </Link>
            <nav className="flex items-center gap-1">
              {NAV.map((item) => (
                <Link
                  key={item.href}
                  href={item.href}
                  className="rounded-md px-3 py-1.5 body-sm text-ink-muted transition-colors hover:bg-muted hover:text-ink-soft"
                >
                  {item.label}
                </Link>
              ))}
            </nav>
          </div>
        </header>
        <main className="mx-auto max-w-7xl px-6 py-8">{children}</main>
      </body>
    </html>
  );
}
