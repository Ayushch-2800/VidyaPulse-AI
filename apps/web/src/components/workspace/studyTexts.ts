import { useEffect, useState } from "react";

import {
  apiFetch,
  type ArtifactRow,
  type CheatSheetContent,
  type Flashcard,
  type QuizQuestion,
  type SummaryContent,
} from "@/lib/workspace";

import { cheatSheetTexts } from "./CheatSheetPanel";

export { cheatSheetTexts };

// The texts each panel shows in the chosen language. The panels and the whole-lecture
// translation below use the same lists, so one request covers every panel.

export const summaryTexts = (content: SummaryContent) => [content.answer];

export const flashcardTexts = (cards: Flashcard[]) =>
  cards.flatMap((card) => [card.question, card.answer]);

export const quizTexts = (questions: QuizQuestion[]) =>
  questions.flatMap((q) => [
    q.question,
    ...q.options,
    ...q.option_explanations,
  ]);

type StudyRows = {
  summary?: ArtifactRow<SummaryContent>;
  flashcards?: ArtifactRow<Flashcard[]>;
  quiz?: ArtifactRow<QuizQuestion[]>;
};

const NO_TEXTS: string[] = [];

function completed<T>(row: ArtifactRow<T> | undefined): T | null {
  return row?.status === "completed" ? row.content : null;
}

/**
 * Every text of a lecture's summary, cheat sheet, flashcards and quiz, loaded while `enabled`
 * (a language other than English is chosen), so the workspace can translate them all in one go
 * instead of one panel at a time.
 */
export function useLectureStudyTexts(
  lectureId: string | null,
  enabled: boolean,
): string[] {
  const [loaded, setLoaded] = useState<{
    lectureId: string;
    texts: string[];
  } | null>(null);

  useEffect(() => {
    if (!lectureId || !enabled) return;
    let cancelled = false;
    const id = encodeURIComponent(lectureId);
    Promise.allSettled([
      apiFetch<StudyRows>(`/lectures/${id}/study-artifacts`),
      apiFetch<ArtifactRow<CheatSheetContent>>(`/lectures/${id}/cheatsheet`),
    ]).then(([study, sheet]) => {
      if (cancelled) return;
      const texts: string[] = [];
      if (study.status === "fulfilled") {
        const summary = completed(study.value.summary);
        const cards = completed(study.value.flashcards);
        const quiz = completed(study.value.quiz);
        if (summary) texts.push(...summaryTexts(summary));
        if (cards) texts.push(...flashcardTexts(cards));
        if (quiz) texts.push(...quizTexts(quiz));
      }
      const content = sheet.status === "fulfilled" && completed(sheet.value);
      if (content) texts.push(...cheatSheetTexts(content));
      setLoaded({ lectureId, texts });
    });
    return () => {
      cancelled = true;
    };
  }, [lectureId, enabled]);

  return enabled && loaded?.lectureId === lectureId ? loaded.texts : NO_TEXTS;
}
