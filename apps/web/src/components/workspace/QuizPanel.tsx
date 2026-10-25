"use client";

import CitedAnswer, { SeekButton } from "@/components/chat/CitedAnswer";
import { useTranslation } from "@/lib/translate";
import {
  formatTimestamp,
  useArtifact,
  type QuizQuestion,
} from "@/lib/workspace";
import { usePersistentState } from "@/lib/workspaceState";

import ArtifactFrame from "./ArtifactFrame";
import InlineMath from "./InlineMath";
import TranslationNote from "./TranslationNote";
import { quizTexts } from "./studyTexts";
import { itemStyle, mutedText, secondaryButton } from "./styles";

export const OPTION_LETTERS = ["A", "B", "C", "D"];

const NO_ANSWERS: Record<number, number> = {};

function optionColors(
  isChosen: boolean,
  isCorrect: boolean,
  answered: boolean,
): React.CSSProperties {
  if (answered && isCorrect)
    return {
      backgroundColor: "var(--vp-success-bg)",
      borderColor: "var(--vp-success)",
    };
  if (answered && isChosen)
    return {
      backgroundColor: "var(--vp-danger-bg)",
      borderColor: "var(--vp-danger)",
    };
  return {
    backgroundColor: "var(--vp-field-bg)",
    borderColor: "var(--vp-border-strong)",
  };
}

/** The Task 16 multiple-choice quiz: answer each question, then read why each option is right or wrong. */
export default function QuizPanel({
  lectureId,
  active,
  onSeek,
}: {
  lectureId: string;
  active: boolean;
  onSeek: (seconds: number) => void;
}) {
  const artifact = useArtifact<QuizQuestion[]>(lectureId, "quiz", active);
  const questions =
    artifact.row?.status === "completed" ? artifact.row.content : [];
  const translation = useTranslation(quizTexts(questions), active);
  const { t } = translation;
  // The option index the student chose for each question, keyed by question position. Kept
  // for this version of the quiz when the student leaves the workspace and comes back.
  const [chosen, setChosen] = usePersistentState(
    artifact.row?.status === "completed"
      ? `quiz:${lectureId}:${artifact.row.updated_at}`
      : null,
    NO_ANSWERS,
  );

  const answeredCount = Object.keys(chosen).length;
  const score = questions.filter(
    (q, i) => chosen[i] === q.correct_index,
  ).length;

  return (
    <ArtifactFrame
      artifact={artifact}
      name="flashcards and quiz"
      wait="about a minute"
    >
      {() =>
        !questions.length ? (
          <p style={{ margin: 0, ...mutedText }}>
            Gemini returned no quiz questions for this lecture.
          </p>
        ) : (
          <>
            <TranslationNote translation={translation}>
              <div style={{ display: "grid", gap: "12px" }}>
                {questions.map((q, qi) => {
                  const answered = qi in chosen;
                  return (
                    <div key={qi} style={itemStyle}>
                      <div
                        style={{
                          display: "flex",
                          justifyContent: "space-between",
                          alignItems: "baseline",
                          gap: "8px",
                        }}
                      >
                        <p style={{ margin: 0, fontWeight: 600 }}>
                          {qi + 1}. <InlineMath text={t(q.question)} />
                        </p>
                        {q.timestamp_seconds !== null && (
                          <SeekButton
                            label={formatTimestamp(q.timestamp_seconds)}
                            seconds={q.timestamp_seconds}
                            onSeek={onSeek}
                          />
                        )}
                      </div>
                      <div
                        style={{
                          display: "grid",
                          gap: "6px",
                          marginTop: "8px",
                        }}
                      >
                        {q.options.map((option, oi) => (
                          <button
                            key={oi}
                            type="button"
                            className="vp-quiz-option"
                            disabled={answered}
                            onClick={() =>
                              setChosen((prev) => ({ ...prev, [qi]: oi }))
                            }
                            style={{
                              display: "flex",
                              gap: "8px",
                              textAlign: "left",
                              padding: "10px 12px",
                              border: "1px solid",
                              borderRadius: "10px",
                              color: "var(--vp-text)",
                              font: "inherit",
                              cursor: answered ? "default" : "pointer",
                              ...optionColors(
                                chosen[qi] === oi,
                                oi === q.correct_index,
                                answered,
                              ),
                            }}
                          >
                            <strong>{OPTION_LETTERS[oi]}.</strong>
                            <InlineMath text={t(option)} />
                          </button>
                        ))}
                      </div>
                      {answered && (
                        <div style={{ marginTop: "10px", fontSize: "0.92em" }}>
                          <p style={{ margin: "0 0 6px", fontWeight: 600 }}>
                            {chosen[qi] === q.correct_index
                              ? "✓ Correct."
                              : `✗ Not quite. The answer is ${OPTION_LETTERS[q.correct_index]}.`}
                          </p>
                          {q.option_explanations.map((why, oi) => (
                            <div
                              key={oi}
                              style={{
                                display: "flex",
                                gap: "6px",
                                marginBottom: "4px",
                                color:
                                  oi === q.correct_index
                                    ? "var(--vp-success)"
                                    : "var(--vp-text-2)",
                              }}
                            >
                              <strong>{OPTION_LETTERS[oi]}:</strong>
                              <CitedAnswer answer={t(why)} onSeek={onSeek} />
                            </div>
                          ))}
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
              <div
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: "12px",
                  marginTop: "12px",
                }}
              >
                <strong>
                  Score: {score} / {questions.length}
                  {answeredCount < questions.length &&
                    ` (${questions.length - answeredCount} left)`}
                </strong>
                {answeredCount > 0 && (
                  <button
                    type="button"
                    onClick={() => setChosen({})}
                    style={secondaryButton}
                  >
                    Retake quiz
                  </button>
                )}
              </div>
            </TranslationNote>
          </>
        )
      }
    </ArtifactFrame>
  );
}
