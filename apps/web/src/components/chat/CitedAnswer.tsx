"use client";

import ReactMarkdown, { type Components } from "react-markdown";
import remarkMath from "remark-math";
import rehypeKatex from "rehype-katex";
import "katex/dist/katex.min.css";

import {
  linkifyCitations,
  normalizeDisplayMath,
  seekSecondsFromHref,
  type Citation,
} from "@/lib/citations";

const NOT_COVERED = "Not covered in this lecture.";

const seekButtonStyle: React.CSSProperties = {
  margin: "0 2px",
  padding: "1px 8px",
  borderRadius: "999px",
  border: "1px solid var(--vp-seek-border)",
  backgroundColor: "var(--vp-seek-bg)",
  color: "var(--vp-seek-text)",
  fontSize: "0.85em",
  fontVariantNumeric: "tabular-nums",
  cursor: "pointer",
  verticalAlign: "baseline",
};

export function SeekButton({
  label,
  seconds,
  onSeek,
  seekUrl,
}: {
  label: string;
  seconds: number;
  onSeek?: (seconds: number) => void;
  seekUrl?: (seconds: number) => string | null;
}) {
  // Without a player (the PDF export), a citation is a link to that moment, or plain text
  if (!onSeek) {
    const href = seekUrl?.(seconds);
    return href ? (
      <a href={href} target="_blank" rel="noopener noreferrer">
        [{label}]
      </a>
    ) : (
      <span>[{label}]</span>
    );
  }
  return (
    <button
      type="button"
      onClick={() => onSeek(seconds)}
      title={`Jump to ${label} in the lecture`}
      aria-label={`Jump to ${label} in the lecture`}
      style={seekButtonStyle}
    >
      ▶ {label}
    </button>
  );
}

/**
 * Renders a synthesizer answer as markdown with KaTeX math, turning every [MM:SS]
 * citation into a button that calls onSeek(seconds) on the lecture player, or into a
 * seekUrl(seconds) link when there is no player.
 */
export default function CitedAnswer({
  answer,
  citations = [],
  onSeek,
  seekUrl,
}: {
  answer: string;
  citations?: Citation[];
  onSeek?: (seconds: number) => void;
  seekUrl?: (seconds: number) => string | null;
}) {
  if (answer.trim() === NOT_COVERED) {
    return (
      <p style={{ margin: 0, color: "var(--vp-muted)", fontStyle: "italic" }}>
        {NOT_COVERED}
      </p>
    );
  }

  const components: Components = {
    a({ href, children }) {
      const seconds = seekSecondsFromHref(href);
      if (seconds !== null) {
        return (
          <SeekButton
            label={String(children)}
            seconds={seconds}
            onSeek={onSeek}
            seekUrl={seekUrl}
          />
        );
      }
      return (
        <a href={href} target="_blank" rel="noopener noreferrer">
          {children}
        </a>
      );
    },
  };

  return (
    <div className="cited-answer" style={{ lineHeight: 1.6 }}>
      <ReactMarkdown
        remarkPlugins={[remarkMath]}
        rehypePlugins={[rehypeKatex]}
        components={components}
      >
        {linkifyCitations(normalizeDisplayMath(answer))}
      </ReactMarkdown>

      {citations.length > 0 && (
        <div
          style={{
            display: "flex",
            flexWrap: "wrap",
            alignItems: "center",
            gap: "6px",
            marginTop: "8px",
            fontSize: "0.9em",
            color: "var(--vp-muted)",
          }}
        >
          <span>Sources:</span>
          {[...citations]
            .sort((a, b) => a.seconds - b.seconds)
            .map((c) => (
              <SeekButton
                key={c.seconds}
                label={c.label}
                seconds={c.seconds}
                onSeek={onSeek}
                seekUrl={seekUrl}
              />
            ))}
        </div>
      )}
    </div>
  );
}
