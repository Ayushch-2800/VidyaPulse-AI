"use client";

import { useEffect, useRef, useState } from "react";

import { API_URL } from "@/lib/api";

export type TranscriptSegment = { start: number; end: number; text: string };

// After the user scrolls the panel themselves, leave it alone for this long
const MANUAL_SCROLL_PAUSE_MS = 4000;

function formatTimestamp(seconds: number): string {
  const total = Math.max(0, Math.floor(seconds));
  const mm = String(Math.floor(total / 60)).padStart(2, "0");
  const ss = String(total % 60).padStart(2, "0");
  return `${mm}:${ss}`;
}

/**
 * Index of the segment playing at `time`: the last one that has started.
 * Between two segments the earlier one stays highlighted; before the first, none is.
 */
export function activeSegmentIndex(
  segments: TranscriptSegment[],
  time: number,
): number {
  let low = 0;
  let high = segments.length - 1;
  let found = -1;
  while (low <= high) {
    const mid = (low + high) >> 1;
    if (segments[mid].start <= time) {
      found = mid;
      low = mid + 1;
    } else {
      high = mid - 1;
    }
  }
  return found;
}

type LoadState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; segments: TranscriptSegment[] };

/**
 * Shows the lecture transcript next to the player, highlights the segment being
 * spoken, keeps it scrolled into view, and seeks the player when a segment is clicked.
 */
export default function TranscriptSidebar({
  lectureId,
  currentTime,
  onSeek,
}: {
  lectureId: string;
  currentTime: number;
  onSeek: (seconds: number) => void;
}) {
  const [state, setState] = useState<LoadState>({ status: "loading" });
  const panel = useRef<HTMLDivElement>(null);
  const segmentRefs = useRef<(HTMLButtonElement | null)[]>([]);
  const lastManualScroll = useRef(0);

  useEffect(() => {
    const controller = new AbortController();
    fetch(`${API_URL}/lectures/${encodeURIComponent(lectureId)}/transcript`, {
      signal: controller.signal,
    })
      .then(async (response) => {
        const data = await response.json();
        if (!response.ok)
          throw new Error(data.detail || "Could not load the transcript.");
        setState({ status: "ready", segments: data.segments });
      })
      .catch((err) => {
        if (controller.signal.aborted) return;
        setState({
          status: "error",
          message: err instanceof Error ? err.message : String(err),
        });
      });
    return () => controller.abort();
  }, [lectureId]);

  const segments = state.status === "ready" ? state.segments : [];
  const active = activeSegmentIndex(segments, currentTime);

  useEffect(() => {
    const container = panel.current;
    const element = segmentRefs.current[active];
    if (!container || !element) return;
    if (Date.now() - lastManualScroll.current < MANUAL_SCROLL_PAUSE_MS) return;
    // Scroll only the panel (scrollIntoView would also scroll the page) and keep
    // the active segment about a third of the way down so upcoming text shows
    container.scrollTo({
      top: element.offsetTop - container.clientHeight / 3,
      behavior: "smooth",
    });
  }, [active]);

  const markManualScroll = () => {
    lastManualScroll.current = Date.now();
  };

  return (
    <aside
      style={{
        display: "flex",
        flexDirection: "column",
        border: "1px solid #E5E7EB",
        borderRadius: "8px",
        backgroundColor: "#fff",
        minHeight: 0,
        height: "100%",
      }}
    >
      <h2
        style={{
          margin: 0,
          padding: "12px 16px",
          fontSize: "1rem",
          fontWeight: 600,
          borderBottom: "1px solid #E5E7EB",
        }}
      >
        Transcript
      </h2>
      <div
        ref={panel}
        onWheel={markManualScroll}
        onTouchMove={markManualScroll}
        style={{
          position: "relative",
          flex: 1,
          overflowY: "auto",
          padding: "8px",
        }}
      >
        {state.status === "loading" && (
          <p style={{ margin: "8px", color: "#6B7280" }}>Loading transcript…</p>
        )}
        {state.status === "error" && (
          <p style={{ margin: "8px", color: "#B91C1C" }}>{state.message}</p>
        )}
        {segments.map((segment, i) => {
          const isActive = i === active;
          return (
            <button
              key={`${segment.start}-${i}`}
              ref={(el) => {
                segmentRefs.current[i] = el;
              }}
              type="button"
              onClick={() => onSeek(segment.start)}
              aria-current={isActive ? "true" : undefined}
              title={`Jump to ${formatTimestamp(segment.start)}`}
              style={{
                display: "block",
                width: "100%",
                textAlign: "left",
                padding: "8px 10px",
                marginBottom: "4px",
                border: "none",
                borderLeft: `3px solid ${isActive ? "#0070f3" : "transparent"}`,
                borderRadius: "4px",
                backgroundColor: isActive ? "#EFF6FF" : "transparent",
                color: isActive ? "#111827" : "#374151",
                font: "inherit",
                lineHeight: 1.5,
                cursor: "pointer",
              }}
            >
              <span
                style={{
                  display: "block",
                  fontSize: "0.75em",
                  color: "#0070f3",
                  fontVariantNumeric: "tabular-nums",
                }}
              >
                {formatTimestamp(segment.start)}
              </span>
              {segment.text}
            </button>
          );
        })}
      </div>
    </aside>
  );
}
