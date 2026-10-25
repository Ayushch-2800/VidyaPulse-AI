"use client";

import { useState } from "react";

import { errorMessage, type NewNote } from "@/lib/workspace";

import { errorText, secondaryButton } from "./styles";

/** "Save to notes" for an answer, flashcard or formula. */
export default function SaveNoteButton({
  note,
  onSave,
}: {
  note: NewNote;
  onSave: (note: NewNote) => Promise<unknown>;
}) {
  const [state, setState] = useState<"idle" | "saving" | "saved">("idle");
  const [error, setError] = useState<string | null>(null);

  const save = () => {
    setState("saving");
    setError(null);
    onSave(note).then(
      () => setState("saved"),
      (err) => {
        setState("idle");
        setError(errorMessage(err));
      },
    );
  };

  return (
    <span>
      <button
        type="button"
        onClick={save}
        disabled={state !== "idle"}
        style={{
          ...secondaryButton,
          ...(state === "saved"
            ? {
                color: "var(--vp-success)",
                borderColor: "var(--vp-success)",
                cursor: "default",
              }
            : {}),
        }}
      >
        {state === "saved"
          ? "✓ Saved to notes"
          : state === "saving"
            ? "Saving…"
            : "☆ Save to notes"}
      </button>
      {error && (
        <span style={{ marginLeft: "8px", fontSize: "0.85em", ...errorText }}>
          {error}
        </span>
      )}
    </span>
  );
}
