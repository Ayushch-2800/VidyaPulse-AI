"use client";

import CitedAnswer, { SeekButton } from "@/components/chat/CitedAnswer";
import { useTranslation } from "@/lib/translate";
import {
  formatTimestamp,
  useArtifact,
  type CheatSheetContent,
  type CheatSheetItem,
  type NewNote,
} from "@/lib/workspace";

import ArtifactFrame from "./ArtifactFrame";
import InlineMath from "./InlineMath";
import MathBlock from "./MathBlock";
import SaveNoteButton from "./SaveNoteButton";
import TranslationNote from "./TranslationNote";
import { chipStyle, itemStyle, mutedText } from "./styles";

export const CHEAT_SHEET_SECTIONS = [
  { key: "definitions", heading: "Definitions" },
  { key: "theorems", heading: "Theorems and laws" },
  { key: "formulas", heading: "Formulas" },
] as const;

export function cheatSheetItems(content: CheatSheetContent): CheatSheetItem[] {
  return CHEAT_SHEET_SECTIONS.flatMap((s) => content[s.key] ?? []);
}

/** The texts the cheat sheet shows in the chosen language. */
export const cheatSheetTexts = (content: CheatSheetContent) =>
  cheatSheetItems(content).flatMap((item) => [item.title, item.explanation]);

/** A formula note keeps the LaTeX as display math above the explanation. */
export function itemAsNote(item: CheatSheetItem): NewNote {
  return {
    kind: "formula",
    title: item.title,
    body: [item.latex && `$$${item.latex}$$`, item.explanation]
      .filter(Boolean)
      .join("\n\n"),
    timestamp_seconds: item.timestamp_seconds,
  };
}

/** The Task 15 cheat sheet: definitions, theorems and formulas with exam topic tags. */
export default function CheatSheetPanel({
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
  const artifact = useArtifact<CheatSheetContent>(
    lectureId,
    "cheatsheet",
    active,
  );
  const items =
    artifact.row?.status === "completed"
      ? cheatSheetItems(artifact.row.content)
      : [];
  const translation = useTranslation(
    artifact.row?.status === "completed"
      ? cheatSheetTexts(artifact.row.content)
      : [],
    active,
  );
  const { t } = translation;

  return (
    <ArtifactFrame artifact={artifact} name="cheat sheet" wait="a few minutes">
      {(row) => (
        <>
          <TranslationNote translation={translation}>
            {row.topic_tags && row.topic_tags.length > 0 && (
              <div style={{ marginBottom: "16px" }}>
                <p style={{ margin: "0 0 6px", fontWeight: 600 }}>
                  Exam relevance
                </p>
                <div style={{ display: "flex", flexWrap: "wrap", gap: "6px" }}>
                  {row.topic_tags.map((tag) => (
                    <span
                      key={`${tag.exam}-${tag.subject}-${tag.topic}`}
                      style={chipStyle}
                    >
                      {tag.exam} · {tag.subject} · {tag.topic}
                    </span>
                  ))}
                </div>
              </div>
            )}

            {items.length === 0 && (
              <p style={{ margin: 0, ...mutedText }}>
                Gemini found no definitions, theorems or formulas in this
                lecture.
              </p>
            )}

            {CHEAT_SHEET_SECTIONS.map(({ key, heading }) => {
              const section = row.content[key] ?? [];
              if (!section.length) return null;
              return (
                <section key={key} style={{ marginBottom: "16px" }}>
                  <h3
                    style={{
                      margin: "0 0 8px",
                      fontSize: "1rem",
                      fontWeight: 600,
                    }}
                  >
                    {heading} ({section.length})
                  </h3>
                  <div style={{ display: "grid", gap: "8px" }}>
                    {section.map((item, i) => (
                      <div key={`${item.title}-${i}`} style={itemStyle}>
                        <div
                          style={{
                            display: "flex",
                            justifyContent: "space-between",
                            gap: "8px",
                            alignItems: "baseline",
                          }}
                        >
                          <strong>
                            <InlineMath text={t(item.title)} />
                          </strong>
                          {item.timestamp_seconds !== null && (
                            <SeekButton
                              label={formatTimestamp(item.timestamp_seconds)}
                              seconds={item.timestamp_seconds}
                              onSeek={onSeek}
                            />
                          )}
                        </div>
                        {item.latex && <MathBlock latex={item.latex} />}
                        {item.explanation && (
                          <CitedAnswer
                            answer={t(item.explanation)}
                            onSeek={onSeek}
                          />
                        )}
                        <div
                          style={{
                            display: "flex",
                            flexWrap: "wrap",
                            alignItems: "center",
                            gap: "6px",
                            marginTop: "8px",
                          }}
                        >
                          {(item.exam_topics ?? []).map((topic) => (
                            <span
                              key={`${topic.exam}-${topic.topic}`}
                              style={chipStyle}
                            >
                              {topic.exam} · {topic.topic}
                            </span>
                          ))}
                          <SaveNoteButton
                            note={itemAsNote(item)}
                            onSave={onSaveNote}
                          />
                        </div>
                      </div>
                    ))}
                  </div>
                </section>
              );
            })}
          </TranslationNote>
        </>
      )}
    </ArtifactFrame>
  );
}
