"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";

import Icon from "./Icon";
import { Wordmark } from "./Logo";

const NAV_LINKS = [
  { href: "/#features", label: "Features" },
  { href: "/#how-it-works", label: "How it works" },
  { href: "/#languages", label: "Languages" },
  { href: "/chat", label: "Workspace" },
];

/** The site-wide top bar: brand, section links, log in and the main call to action. */
export default function SiteHeader() {
  const pathname = usePathname();
  const [scrolled, setScrolled] = useState(false);
  const [open, setOpen] = useState(false);
  // The workspace keeps its transcript sticky, so the header scrolls away there
  const inWorkspace = pathname.startsWith("/chat");

  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 8);
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open]);

  const close = () => setOpen(false);
  const current = (href: string) =>
    href === "/chat" && inWorkspace ? "page" : undefined;

  return (
    <header
      className="vp-header no-print"
      data-scrolled={scrolled}
      data-open={open}
      data-static={inWorkspace}
    >
      <div className="vp-container vp-header__bar">
        <Link href="/" className="vp-brand" aria-label="VidyaPulse AI home">
          <Wordmark id="header" />
        </Link>

        <nav className="vp-nav" aria-label="Main">
          {NAV_LINKS.map((link) => (
            <Link
              key={link.href}
              href={link.href}
              aria-current={current(link.href)}
            >
              {link.label}
            </Link>
          ))}
        </nav>

        <div className="vp-header__actions">
          <Link href="/login" className="vp-btn vp-btn-ghost vp-btn-sm">
            Log in
          </Link>
          <Link href="/ingest" className="vp-btn vp-btn-primary vp-btn-sm">
            Add a lecture
            <Icon name="arrowRight" />
          </Link>
        </div>

        <button
          type="button"
          className="vp-menu-button"
          aria-expanded={open}
          aria-controls="vp-mobile-nav"
          aria-label={open ? "Close menu" : "Open menu"}
          onClick={() => setOpen((v) => !v)}
        >
          <Icon name={open ? "close" : "menu"} />
        </button>
      </div>

      {open && (
        <nav id="vp-mobile-nav" className="vp-mobile-nav" aria-label="Main">
          {NAV_LINKS.map((link) => (
            <Link
              key={link.href}
              href={link.href}
              aria-current={current(link.href)}
              onClick={close}
            >
              {link.label}
            </Link>
          ))}
          <Link href="/login" onClick={close}>
            Log in
          </Link>
          <Link
            href="/ingest"
            className="vp-btn vp-btn-primary"
            onClick={close}
            style={{ marginTop: "8px" }}
          >
            Add a lecture
            <Icon name="arrowRight" />
          </Link>
        </nav>
      )}
    </header>
  );
}
