// Matches the [MM:SS] citations produced by the backend synthesizer (minutes may exceed 59)
const TIMESTAMP_PATTERN = /\[(\d{1,3}):([0-5]\d)\](?!\()/g;

// Math and code are copied through untouched so a bracket inside LaTeX is never turned into a link
const PROTECTED_PATTERN =
  /(\$\$[\s\S]*?\$\$|\$[^$\n]+?\$|```[\s\S]*?```|`[^`\n]*`)/g;

export const SEEK_HREF_PREFIX = "#vp-seek-";

export type Citation = { label: string; seconds: number };

export function toSeconds(minutes: string, seconds: string): number {
  return Number(minutes) * 60 + Number(seconds);
}

/**
 * Rewrites every [MM:SS] outside math/code into a markdown link "[MM:SS](#vp-seek-<seconds>)"
 * so the markdown renderer hands it to our custom link component as a seek button.
 */
export function linkifyCitations(markdown: string): string {
  return markdown
    .split(PROTECTED_PATTERN)
    .map((part, i) =>
      // split() with a capture group puts the protected matches at odd indexes
      i % 2 === 1
        ? part
        : part.replace(
            TIMESTAMP_PATTERN,
            (_, mm: string, ss: string) =>
              `[${mm}:${ss}](${SEEK_HREF_PREFIX}${toSeconds(mm, ss)})`,
          ),
    )
    .join("");
}

/**
 * remark-math only renders $$...$$ as a display block when the delimiters sit on their own lines,
 * but Gemini usually writes "$$ ... $$" on one line, so split such lines into the block form.
 */
export function normalizeDisplayMath(markdown: string): string {
  return markdown.replace(
    /^[ \t]*\$\$([^\n]+?)\$\$[ \t]*$/gm,
    "$$$$\n$1\n$$$$",
  );
}

/** Returns the seek target in seconds for a link produced by linkifyCitations, else null. */
export function seekSecondsFromHref(href?: string): number | null {
  if (!href?.startsWith(SEEK_HREF_PREFIX)) return null;
  const seconds = Number(href.slice(SEEK_HREF_PREFIX.length));
  return Number.isFinite(seconds) ? seconds : null;
}
