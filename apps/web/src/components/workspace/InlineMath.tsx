"use client";

import katex from "katex";
import "katex/dist/katex.min.css";

const MATH_PATTERN = /(\$\$[^$]+?\$\$|\$[^$\n]+?\$)/g;

/**
 * Plain text with $...$ math rendered inline. For short strings that sit inside buttons
 * or headings (quiz options, questions, titles), where block markdown cannot go.
 */
export default function InlineMath({ text }: { text: string }) {
  return (
    <span>
      {text.split(MATH_PATTERN).map((part, i) =>
        // split() with a capture group puts the math at odd indexes
        i % 2 === 1 ? (
          <span
            key={i}
            dangerouslySetInnerHTML={{
              __html: katex.renderToString(part.replace(/^\$\$?|\$?\$$/g, ""), {
                throwOnError: false,
              }),
            }}
          />
        ) : (
          part
        ),
      )}
    </span>
  );
}
