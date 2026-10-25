"use client";

import katex from "katex";
import "katex/dist/katex.min.css";

/** Renders one LaTeX expression (no $ delimiters) as display math. */
export default function MathBlock({ latex }: { latex: string }) {
  return (
    <div
      style={{ overflowX: "auto", margin: "8px 0" }}
      dangerouslySetInnerHTML={{
        __html: katex.renderToString(latex, {
          displayMode: true,
          throwOnError: false,
        }),
      }}
    />
  );
}
