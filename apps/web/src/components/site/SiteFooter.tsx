import Link from "next/link";

import { Wordmark } from "./Logo";

const COLUMNS = [
  {
    heading: "Study",
    links: [
      { href: "/chat", label: "Lecture workspace" },
      { href: "/ingest", label: "Add a YouTube lecture" },
      { href: "/upload", label: "Upload a recording" },
      { href: "/login", label: "Log in or sign up" },
    ],
  },
  {
    heading: "Explore",
    links: [
      { href: "/#features", label: "Features" },
      { href: "/#how-it-works", label: "How it works" },
      { href: "/#languages", label: "Languages" },
      { href: "/#faq", label: "FAQ" },
    ],
  },
];

/** Site footer. The build line shows which commit is served, and in development which checkout too. */
export default function SiteFooter() {
  const dev = process.env.NODE_ENV !== "production";
  return (
    <footer className="vp-footer no-print">
      <div className="vp-container grid gap-10 py-14 md:grid-cols-4">
        <div className="md:col-span-2">
          <Link href="/" className="vp-brand" aria-label="VidyaPulse AI home">
            <Wordmark id="footer" />
          </Link>
          <p className="mt-4 max-w-sm">
            Lecture intelligence for Indian classrooms. Ask doubts, revise and
            export notes from any lecture, in the language you think in.
          </p>
        </div>
        {COLUMNS.map((column) => (
          <nav key={column.heading} aria-label={column.heading}>
            <h2>{column.heading}</h2>
            <ul className="grid gap-2.5">
              {column.links.map((link) => (
                <li key={link.href}>
                  <Link href={link.href}>{link.label}</Link>
                </li>
              ))}
            </ul>
          </nav>
        ))}
      </div>
      <div
        className="vp-container flex flex-wrap justify-between gap-2 py-5 text-xs text-muted"
        style={{ borderTop: "1px solid var(--vp-border)" }}
      >
        <span>
          © {new Date().getFullYear()} VidyaPulse AI. Made for students in
          India.
        </span>
        <span>
          Build {process.env.NEXT_PUBLIC_BUILD_COMMIT}
          {dev && (
            <>
              {" "}
              · served from {process.env.NEXT_PUBLIC_BUILD_DIR} · started{" "}
              {process.env.NEXT_PUBLIC_BUILD_TIME}
            </>
          )}
        </span>
      </div>
    </footer>
  );
}
