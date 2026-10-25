/**
 * The VidyaPulse mark: a pulse line whose dip draws a V, on the brand gradient.
 * `id` keeps the gradient reference unique when the mark appears more than once,
 * since a gradient defined inside a hidden SVG stops painting everywhere else.
 */
export function LogoMark({
  id,
  className,
}: {
  id: string;
  className?: string;
}) {
  const gradient = `vp-logo-${id}`;
  return (
    <svg
      viewBox="0 0 48 48"
      className={className}
      aria-hidden="true"
      focusable="false"
    >
      <defs>
        <linearGradient
          id={gradient}
          x1="0"
          y1="0"
          x2="48"
          y2="48"
          gradientUnits="userSpaceOnUse"
        >
          <stop offset="0" stopColor="#7c3aed" />
          <stop offset="0.55" stopColor="#db2777" />
          <stop offset="1" stopColor="#f59e0b" />
        </linearGradient>
      </defs>
      <rect width="48" height="48" rx="14" fill={`url(#${gradient})`} />
      <rect
        x="1"
        y="1"
        width="46"
        height="46"
        rx="13"
        fill="none"
        stroke="rgba(255,255,255,0.28)"
      />
      <path
        className="vp-logo__pulse"
        d="M8 25h7l3-7 6 16 6-22 3 13h7"
        fill="none"
        stroke="#fff"
        strokeWidth="3.2"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

/** The mark with the wordmark beside it, as used in the header and footer. */
export function Wordmark({ id }: { id: string }) {
  return (
    <>
      <LogoMark id={id} />
      <span>
        VidyaPulse<span className="vp-brand__ai">AI</span>
      </span>
    </>
  );
}
