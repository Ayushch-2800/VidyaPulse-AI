import type { Metadata, Viewport } from "next";
import { Inter, Sora } from "next/font/google";

import AnimatedBackground from "@/components/site/AnimatedBackground";
import { INTRO_HEAD_SCRIPT } from "@/components/site/intro";
import SiteFooter from "@/components/site/SiteFooter";
import SiteHeader from "@/components/site/SiteHeader";

import "./globals.css";

const inter = Inter({
  subsets: ["latin"],
  variable: "--font-inter",
  display: "swap",
});

const sora = Sora({
  subsets: ["latin"],
  weight: ["600", "700", "800"],
  variable: "--font-sora",
  display: "swap",
});

const SITE_URL = process.env.NEXT_PUBLIC_SITE_URL || "http://localhost:3000";
const DESCRIPTION =
  "Turn any lecture into cited answers, summaries, cheat sheets, flashcards and quizzes, in English, Hindi, Tamil, Telugu, Marathi or Bengali. Built for JEE, NEET, GATE and UPSC students.";

export const metadata: Metadata = {
  metadataBase: new URL(SITE_URL),
  title: {
    default: "VidyaPulse AI · Stop rewinding lectures, start mastering them",
    template: "%s · VidyaPulse AI",
  },
  description: DESCRIPTION,
  applicationName: "VidyaPulse AI",
  keywords: [
    "lecture notes",
    "AI study assistant",
    "JEE",
    "NEET",
    "GATE",
    "UPSC",
    "Hinglish",
    "flashcards",
    "cheat sheet",
  ],
  openGraph: {
    type: "website",
    siteName: "VidyaPulse AI",
    locale: "en_IN",
    title: "VidyaPulse AI · Stop rewinding lectures, start mastering them",
    description: DESCRIPTION,
  },
  twitter: {
    card: "summary_large_image",
    title: "VidyaPulse AI",
    description: DESCRIPTION,
  },
};

export const viewport: Viewport = {
  themeColor: "#07051a",
  colorScheme: "dark",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    // The head script may mark the intro as seen before React loads
    <html
      lang="en"
      className={`${inter.variable} ${sora.variable}`}
      suppressHydrationWarning
    >
      <head>
        <script dangerouslySetInnerHTML={{ __html: INTRO_HEAD_SCRIPT }} />
      </head>
      <body>
        <a href="#main" className="vp-skip-link">
          Skip to content
        </a>
        <AnimatedBackground />
        <div className="vp-shell">
          <SiteHeader />
          <main id="main">{children}</main>
          <SiteFooter />
        </div>
      </body>
    </html>
  );
}
