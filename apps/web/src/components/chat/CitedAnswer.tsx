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
  border: "1px solid #0070f3",
  backgroundColor: "#EFF6FF",
  color: "#0070f3",
  fontSize: "0.85em",
  fontVariantNumeric: "tabular-nums",
  cursor: "pointer",
  verticalAlign: "baseline",
};

function SeekButton({
  label,
  seconds,
  onSeek,
}: {
  label: string;
  seconds: number;
  onSeek: (seconds: number) => void;
}) {
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
 * citation into a button that calls onSeek(seconds) on the lecture player.
 */
export default function CitedAnswer({
  answer,
  citations = [],
  onSeek,
}: {
  answer: string;
  citations?: Citation[];
  onSeek: (seconds: number) => void;
}) {
  if (answer.trim() === NOT_COVERED) {
    return (
      <p style={{ margin: 0, color: "#6B7280", fontStyle: "italic" }}>
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
    <div style={{ lineHeight: 1.6 }}>
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
            color: "#6B7280",
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
              />
            ))}
        </div>
      )}
    </div>
  );
}
