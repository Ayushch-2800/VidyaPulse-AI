"use client";

import {
  STALL_MINUTES,
  formatTimestamp,
  useElapsedSeconds,
  type Artifact,
  type ArtifactRow,
} from "@/lib/workspace";

import { errorText, mutedText, primaryButton, secondaryButton } from "./styles";

/**
 * The loading, not-generated-yet, generating and failed states shared by the summary,
 * cheat sheet, flashcards and quiz panels. Renders children once the content is ready.
 */
export default function ArtifactFrame<T>({
  artifact,
  name,
  wait,
  slowAfterSeconds,
  slowNote,
  children,
}: {
  artifact: Artifact<T>;
  /** What is generated, e.g. "cheat sheet"; used in the messages and buttons. */
  name: string;
  /** How long generation usually takes, e.g. "about a minute". */
  wait: string;
  /** After this many seconds, show slowNote under the progress line. */
  slowAfterSeconds?: number;
  /** What the backend does when Gemini is slow, e.g. that it switches to a faster model. */
  slowNote?: string;
  children: (row: ArtifactRow<T>) => React.ReactNode;
}) {
  const {
    row,
    loading,
    error,
    generating,
    startedAt,
    stalled,
    generate,
    reload,
  } = artifact;
  const elapsed = useElapsedSeconds(stalled ? null : startedAt);

  if (loading) return <p style={{ margin: 0, ...mutedText }}>Loading…</p>;

  if (stalled) {
    return (
      <div>
        <p style={{ marginTop: 0, ...errorText }}>
          The {name} has been in progress for over {STALL_MINUTES} minutes, so
          the job most likely stopped (for example when the backend restarted).
          Check the backend terminal for an error, then try again.
        </p>
        <button type="button" onClick={generate} style={primaryButton}>
          Try again
        </button>
      </div>
    );
  }

  if (generating) {
    const slow =
      slowNote !== undefined &&
      elapsed !== null &&
      elapsed >= (slowAfterSeconds ?? 60);
    return (
      <div>
        <p style={{ margin: 0, ...mutedText }}>
          ⏳ Generating the {name} with Gemini
          {elapsed !== null && <> ({formatTimestamp(elapsed)} so far)</>}. This
          usually takes {wait} on the free tier; it appears here when ready.
        </p>
        {slow && <p style={{ margin: "8px 0 0", ...mutedText }}>{slowNote}</p>}
      </div>
    );
  }

  if (!row) {
    return (
      <div>
        {error ? (
          <p style={{ marginTop: 0, ...errorText }}>{error}</p>
        ) : (
          <p style={{ marginTop: 0, ...mutedText }}>
            No {name} for this lecture yet.
          </p>
        )}
        <button type="button" onClick={generate} style={primaryButton}>
          Generate {name}
        </button>{" "}
        {error && (
          <button type="button" onClick={reload} style={secondaryButton}>
            Reload
          </button>
        )}
      </div>
    );
  }

  if (row.status === "failed") {
    return (
      <div>
        <p style={{ marginTop: 0, ...errorText }}>
          Generating the {name} failed: {row.error || error || "unknown error"}
        </p>
        <button type="button" onClick={generate} style={primaryButton}>
          Try again
        </button>
      </div>
    );
  }

  return (
    <div>
      {error && <p style={{ marginTop: 0, ...errorText }}>{error}</p>}
      {children(row)}
      <p style={{ margin: "16px 0 0", fontSize: "0.85em", ...mutedText }}>
        Generated {new Date(row.updated_at).toLocaleString()}
        {row.model && <> with {row.model}</>}.{" "}
        <button type="button" onClick={generate} style={secondaryButton}>
          Regenerate
        </button>
      </p>
    </div>
  );
}
