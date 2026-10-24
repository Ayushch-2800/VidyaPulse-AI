"use client";

// Matches the [MM:SS] citations produced by the backend synthesizer (minutes may exceed 59)
const TIMESTAMP_PATTERN = /\[(\d{1,3}):([0-5]\d)\]/g;

type Segment =
  | { type: "text"; value: string }
  | { type: "timestamp"; label: string; seconds: number };

export function splitCitations(answer: string): Segment[] {
  const segments: Segment[] = [];
  let lastIndex = 0;

  for (const match of answer.matchAll(TIMESTAMP_PATTERN)) {
    const index = match.index ?? 0;
    if (index > lastIndex) {
      segments.push({ type: "text", value: answer.slice(lastIndex, index) });
    }
    segments.push({
      type: "timestamp",
      label: `${match[1]}:${match[2]}`,
      seconds: Number(match[1]) * 60 + Number(match[2]),
    });
    lastIndex = index + match[0].length;
  }

  if (lastIndex < answer.length) {
    segments.push({ type: "text", value: answer.slice(lastIndex) });
  }
  return segments;
}

export default function CitedAnswer({
  answer,
  onSeek,
}: {
  answer: string;
  onSeek: (seconds: number) => void;
}) {
  return (
    <p style={{ whiteSpace: "pre-wrap", lineHeight: 1.6, margin: 0 }}>
      {splitCitations(answer).map((segment, i) =>
        segment.type === "text" ? (
          <span key={i}>{segment.value}</span>
        ) : (
          <button
            key={i}
            type="button"
            onClick={() => onSeek(segment.seconds)}
            title={`Jump to ${segment.label} in the lecture`}
            style={{
              margin: "0 2px",
              padding: "1px 8px",
              borderRadius: "999px",
              border: "1px solid #0070f3",
              backgroundColor: "#EFF6FF",
              color: "#0070f3",
              fontSize: "0.85em",
              cursor: "pointer",
            }}
          >
            ▶ {segment.label}
          </button>
        ),
      )}
    </p>
  );
}
