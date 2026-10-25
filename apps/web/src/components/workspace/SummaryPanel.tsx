"use client";

import CitedAnswer from "@/components/chat/CitedAnswer";
import { useTranslation } from "@/lib/translate";
import {
  useArtifact,
  type NewNote,
  type SummaryContent,
} from "@/lib/workspace";

import ArtifactFrame from "./ArtifactFrame";
import SaveNoteButton from "./SaveNoteButton";
import TranslationNote from "./TranslationNote";

/** The stored lecture summary, with [MM:SS] buttons, in the chosen language. */
export default function SummaryPanel({
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
  const artifact = useArtifact<SummaryContent>(lectureId, "summary", active);
  const answer =
    artifact.row?.status === "completed" ? artifact.row.content.answer : "";
  const translation = useTranslation([answer], active);

  return (
    <ArtifactFrame
      artifact={artifact}
      name="summary"
      wait="under a minute"
      slowAfterSeconds={60}
      slowNote="Gemini's free tier is slow right now, so the backend tries a faster model after a minute and keeps trying for up to about three minutes. You can use the other tabs meanwhile."
    >
      {(row) => (
        <>
          <TranslationNote translation={translation} />
          <CitedAnswer
            answer={translation.t(row.content.answer)}
            citations={row.content.citations}
            onSeek={onSeek}
          />
          <div style={{ marginTop: "12px" }}>
            <SaveNoteButton
              note={{
                kind: "answer",
                title: "Lecture summary",
                body: row.content.answer,
                timestamp_seconds: null,
              }}
              onSave={onSaveNote}
            />
          </div>
        </>
      )}
    </ArtifactFrame>
  );
}
