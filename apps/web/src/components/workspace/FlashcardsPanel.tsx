"use client";

import CitedAnswer, { SeekButton } from "@/components/chat/CitedAnswer";
import { useTranslation } from "@/lib/translate";
import {
  formatTimestamp,
  useArtifact,
  type Flashcard,
  type NewNote,
} from "@/lib/workspace";
import { usePersistentState } from "@/lib/workspaceState";

import ArtifactFrame from "./ArtifactFrame";
import InlineMath from "./InlineMath";
import SaveNoteButton from "./SaveNoteButton";
import TranslationNote from "./TranslationNote";
import { itemStyle, mutedText, primaryButton, secondaryButton } from "./styles";

const START = { index: 0, revealed: false };

/** The Task 16 flashcards, one at a time: read the question, recall, then reveal. */
export default function FlashcardsPanel({
  lectureId,
  active,
  onSeek,
  onSaveNote,
}: {
  lectureId: string;
  active: boolean;
  onSeek: (seconds: number) => void;
  onSaveNote: (note: NewNote) => Promise<unknown>;
}) {
  const artifact = useArtifact<Flashcard[]>(lectureId, "flashcards", active);
  const cards =
    artifact.row?.status === "completed" ? artifact.row.content : [];
  const translation = useTranslation(
    cards.flatMap((c) => [c.question, c.answer]),
    active,
  );
  const { t } = translation;
  // Where the student is in this version of the deck, kept when they leave the workspace
  const [{ index, revealed }, setProgress] = usePersistentState(
    artifact.row?.status === "completed"
      ? `flashcards:${lectureId}:${artifact.row.updated_at}`
      : null,
    START,
  );

  const go = (next: number) => setProgress({ index: next, revealed: false });

  return (
    <ArtifactFrame
      artifact={artifact}
      name="flashcards and quiz"
      wait="about a minute"
    >
      {() => {
        if (!cards.length)
          return (
            <p style={{ margin: 0, ...mutedText }}>
              Gemini returned no flashcards for this lecture.
            </p>
          );
        const position = Math.min(index, cards.length - 1);
        const card = cards[position];
        return (
          <>
            <TranslationNote translation={translation} />
            <p style={{ margin: "0 0 8px", ...mutedText }}>
              Card {position + 1} of {cards.length}. Try to answer before you
              reveal it.
            </p>
            <div style={{ ...itemStyle, minHeight: "160px" }}>
              <p style={{ margin: "0 0 12px", fontWeight: 600 }}>
                <InlineMath text={t(card.question)} />
              </p>
              {revealed ? (
                <div
                  style={{
                    borderTop: "1px solid var(--vp-border)",
                    paddingTop: "12px",
                  }}
                >
                  <CitedAnswer answer={t(card.answer)} onSeek={onSeek} />
                  <div
                    style={{
                      display: "flex",
                      flexWrap: "wrap",
                      alignItems: "center",
                      gap: "8px",
                      marginTop: "12px",
                    }}
                  >
                    {card.timestamp_seconds !== null && (
                      <span style={{ fontSize: "0.9em", ...mutedText }}>
                        Proof:{" "}
                        <SeekButton
                          label={formatTimestamp(card.timestamp_seconds)}
                          seconds={card.timestamp_seconds}
                          onSeek={onSeek}
                        />
                      </span>
                    )}
                    <SaveNoteButton
                      key={position}
                      note={{
                        kind: "flashcard",
                        title: card.question,
                        body: card.answer,
                        timestamp_seconds: card.timestamp_seconds,
                      }}
                      onSave={onSaveNote}
                    />
                  </div>
                </div>
              ) : (
                <button
                  type="button"
                  onClick={() => setProgress({ index, revealed: true })}
                  style={primaryButton}
                >
                  Show answer
                </button>
              )}
            </div>
            <div style={{ display: "flex", gap: "8px", marginTop: "12px" }}>
              <button
                type="button"
                onClick={() => go(position - 1)}
                disabled={position === 0}
                style={secondaryButton}
              >
                ← Previous
              </button>
              <button
                type="button"
                onClick={() => go(position + 1)}
                disabled={position === cards.length - 1}
                style={secondaryButton}
              >
                Next →
              </button>
            </div>
          </>
        );
      }}
    </ArtifactFrame>
  );
}
