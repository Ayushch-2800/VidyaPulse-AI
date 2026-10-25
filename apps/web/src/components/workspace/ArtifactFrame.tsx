"use client";

import type { Artifact, ArtifactRow } from "@/lib/workspace";

import { errorText, mutedText, primaryButton, secondaryButton } from "./styles";

/**
 * The loading, not-generated-yet, generating and failed states shared by the summary,
 * cheat sheet, flashcards and quiz panels. Renders children once the content is ready.
 */
export default function ArtifactFrame<T>({
  artifact,
  name,
  wait,
  children,
}: {
  artifact: Artifact<T>;
  /** What is generated, e.g. "cheat sheet"; used in the messages and buttons. */
  name: string;
  /** How long generation usually takes, e.g. "about a minute". */
  wait: string;
  children: (row: ArtifactRow<T>) => React.ReactNode;
}) {
  const { row, loading, error, generating, stalled, generate, reload } =
    artifact;

  if (loading) return <p style={{ margin: 0, ...mutedText }}>Loading…</p>;

  if (stalled) {
    return (
      <div>
        <p style={{ marginTop: 0, ...errorText }}>
          Still generating the {name} after 20 minutes. Check the backend
          terminal for an error, then try again.
        </p>
        <button type="button" onClick={generate} style={primaryButton}>
          Try again
        </button>
      </div>
    );
  }

  if (generating) {
    return (
      <p style={{ margin: 0, ...mutedText }}>
        ⏳ Generating the {name} with Gemini. This takes {wait} on the free
        tier; it appears here when ready.
      </p>
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
        Generated {new Date(row.updated_at).toLocaleString()}.{" "}
        <button type="button" onClick={generate} style={secondaryButton}>
          Regenerate
        </button>
      </p>
    </div>
  );
}
