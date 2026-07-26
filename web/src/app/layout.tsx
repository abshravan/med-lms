import type { Metadata, Viewport } from "next";

import { Providers } from "@/app/providers";

import "./globals.css";

export const metadata: Metadata = {
  title: {
    default: "MedLMS",
    template: "%s · MedLMS",
  },
  description:
    "A modern medical education platform: video lessons, notes, AI flashcards, quizzes, and voice viva practice.",
  // Auth pages must never be indexed, and there is nothing public to index yet.
  robots: { index: false, follow: false },
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en" suppressHydrationWarning>
      <body className="min-h-screen antialiased">
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
