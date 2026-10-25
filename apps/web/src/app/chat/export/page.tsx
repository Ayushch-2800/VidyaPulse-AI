"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";

import CitedAnswer from "@/components/chat/CitedAnswer";
import Icon from "@/components/site/Icon";
import {
  CHEAT_SHEET_SECTIONS,
  cheatSheetItems,
} from "@/components/workspace/CheatSheetPanel";
import InlineMath from "@/components/workspace/InlineMath";
import LanguageSelect from "@/components/workspace/LanguageSelect";
import MathBlock from "@/components/workspace/MathBlock";
import { NOTE_KIND_LABELS } from "@/components/workspace/NotesPanel";
import { OPTION_LETTERS } from "@/components/workspace/QuizPanel";
import TranslationNote from "@/components/workspace/TranslationNote";
import { chipStyle, errorText, mutedText } from "@/components/workspace/styles";
import {
  LanguageContext,
  useLanguagePreference,
  useTranslation,
} from "@/lib/translate";
import {
  apiFetch,
  errorMessage,
  formatTimestamp,
  type ArtifactRow,
  type ExportBundle,
} from "@/lib/workspace";
import { youTubeTimeUrl } from "@/lib/youtube";

// Headings go through the translator with the content, so the PDF is in one language
const HEADINGS = {
  summary: "Summary",
  cheatSheet: "Cheat sheet",
  examRelevance: "Exam relevance",
  flashcards: "Flashcards",
  quiz: "Quiz",
  answerKey: "Answer key",
  notes: "My notes",
};

// Tailwind's reset strips heading sizes and link styles, so the document sets its own
const EXPORT_CSS = `
.export-sheet h2 { font-size: 1.3rem; font-weight: 700; margin: 28px 0 10px; padding-bottom: 4px; border-bottom: 1px solid #E5E7EB; }
.export-sheet h3 { font-size: 1.05rem; font-weight: 600; margin: 16px 0 6px; }
.export-sheet a { color: #1D4ED8; text-decoration: underline; }
@page { margin: 16mm; }
@media print {
  .no-print { display: none !important; }
  body { background: #fff !important; }
  .export-sheet { box-shadow: none !important; margin: 0 !important; max-width: none !important; padding: 0 !important; }
  .export-item { break-inside: avoid; }
  h2 { break-after: avoid; }
}
`;

type LoadState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | {
      status: "ready";
      bundle: ExportBundle;
      autoPrint: boolean;
      exportedAt: string;
    };

function completed<T>(row: ArtifactRow<T> | null): T | null {
  return row?.status === "completed" ? row.content : null;
}

/** Every string the export shows, so one translation request covers the whole document. */
function exportTexts(bundle: ExportBundle): string[] {
  const summary = completed(bundle.summary);
  const sheet = completed(bundle.cheat_sheet);
  return [
    ...Object.values(HEADINGS),
    ...CHEAT_SHEET_SECTIONS.map((s) => s.heading),
    summary?.answer ?? "",
    ...(sheet
      ? cheatSheetItems(sheet).flatMap((i) => [i.title, i.explanation])
      : []),
    ...(completed(bundle.flashcards) ?? []).flatMap((c) => [
      c.question,
      c.answer,
    ]),
    ...(completed(bundle.quiz) ?? []).flatMap((q) => [
      q.question,
      ...q.options,
      q.option_explanations[q.correct_index] ?? "",
    ]),
    ...bundle.notes.flatMap((n) => [n.title, n.body]),
  ];
}

function ExportDocument({
  bundle,
  autoPrint,
  exportedAt,
}: {
  bundle: ExportBundle;
  autoPrint: boolean;
  exportedAt: string;
}) {
  const translation = useTranslation(exportTexts(bundle));
  const { t, translating } = translation;
  const printed = useRef(false);

  const { lecture } = bundle;
  const title = lecture.title || "Lecture";
  const seekUrl = (seconds: number) =>
    lecture.source_url ? youTubeTimeUrl(lecture.source_url, seconds) : null;
  const stamp = (seconds: number | null) => {
    if (seconds === null) return null;
    const label = `[${formatTimestamp(seconds)}]`;
    const href = seekUrl(seconds);
    return (
      <span style={{ fontVariantNumeric: "tabular-nums", ...mutedText }}>
        {" "}
        {href ? (
          <a href={href} target="_blank" rel="noopener noreferrer">
            {label}
          </a>
        ) : (
          label
        )}
      </span>
    );
  };

  // The saved PDF is named after the page title
  useEffect(() => {
    document.title = `${title} · VidyaPulse study notes`;
  }, [title]);

  // Opens the print dialog once, after every translation has arrived. The flag is set when
  // the dialog opens, not when it is scheduled, so a cancelled timer still prints later.
  useEffect(() => {
    if (!autoPrint || translating || printed.current) return;
    const timer = window.setTimeout(() => {
      printed.current = true;
      window.print();
    }, 500);
    return () => window.clearTimeout(timer);
  }, [autoPrint, translating]);

  const summary = completed(bundle.summary);
  const sheet = completed(bundle.cheat_sheet);
  const flashcards = completed(bundle.flashcards) ?? [];
  const quiz = completed(bundle.quiz) ?? [];
  const topicTags = bundle.cheat_sheet?.topic_tags ?? [];
  const empty =
    !summary &&
    !sheet &&
    !flashcards.length &&
    !quiz.length &&
    !bundle.notes.length;

  return (
    <>
      <div className="no-print" style={{ marginBottom: "16px" }}>
        <TranslationNote translation={translation} />
        {bundle.warnings.map((warning) => (
          <p key={warning} style={{ margin: "0 0 8px", ...errorText }}>
            {warning}
          </p>
        ))}
      </div>

      <header style={{ marginBottom: "24px" }}>
        <h1 style={{ fontSize: "1.6rem", fontWeight: 700, margin: "0 0 4px" }}>
          {title}
        </h1>
        <p style={{ margin: 0, fontSize: "0.9em", ...mutedText }}>
          VidyaPulse AI study notes · exported {exportedAt}
          {lecture.source_url?.startsWith("http") && (
            <>
              {" · "}
              <a href={lecture.source_url}>{lecture.source_url}</a>
            </>
          )}
        </p>
      </header>

      {empty && (
        <p style={mutedText}>
          Nothing to export yet. Generate the summary, cheat sheet, flashcards
          or quiz in the workspace, or save some notes, then export again.
        </p>
      )}

      {summary && (
        <section>
          <h2>{t(HEADINGS.summary)}</h2>
          <CitedAnswer answer={t(summary.answer)} seekUrl={seekUrl} />
        </section>
      )}

      {sheet && (
        <section>
          <h2>{t(HEADINGS.cheatSheet)}</h2>
          {topicTags.length > 0 && (
            <p style={{ display: "flex", flexWrap: "wrap", gap: "6px" }}>
              <strong>{t(HEADINGS.examRelevance)}:</strong>
              {topicTags.map((tag) => (
                <span
                  key={`${tag.exam}-${tag.subject}-${tag.topic}`}
                  style={chipStyle}
                >
                  {tag.exam} · {tag.subject} · {tag.topic}
                </span>
              ))}
            </p>
          )}
          {CHEAT_SHEET_SECTIONS.map(({ key, heading }) => {
            const items = sheet[key] ?? [];
            if (!items.length) return null;
            return (
              <div key={key}>
                <h3>{t(heading)}</h3>
                {items.map((item, i) => (
                  <div key={`${item.title}-${i}`} className="export-item">
                    <p style={{ margin: "8px 0 0" }}>
                      <strong>
                        <InlineMath text={t(item.title)} />
                      </strong>
                      {stamp(item.timestamp_seconds)}
                    </p>
                    {item.latex && <MathBlock latex={item.latex} />}
                    {item.explanation && (
                      <CitedAnswer
                        answer={t(item.explanation)}
                        seekUrl={seekUrl}
                      />
                    )}
                  </div>
                ))}
              </div>
            );
          })}
        </section>
      )}

      {flashcards.length > 0 && (
        <section>
          <h2>{t(HEADINGS.flashcards)}</h2>
          {flashcards.map((card, i) => (
            <div
              key={i}
              className="export-item"
              style={{ marginBottom: "12px" }}
            >
              <p style={{ margin: 0, fontWeight: 600 }}>
                Q{i + 1}. <InlineMath text={t(card.question)} />
                {stamp(card.timestamp_seconds)}
              </p>
              <CitedAnswer answer={t(card.answer)} seekUrl={seekUrl} />
            </div>
          ))}
        </section>
      )}

      {quiz.length > 0 && (
        <section>
          <h2>{t(HEADINGS.quiz)}</h2>
          {quiz.map((q, i) => (
            <div
              key={i}
              className="export-item"
              style={{ marginBottom: "12px" }}
            >
              <p style={{ margin: 0, fontWeight: 600 }}>
                {i + 1}. <InlineMath text={t(q.question)} />
                {stamp(q.timestamp_seconds)}
              </p>
              {q.options.map((option, oi) => (
                <p key={oi} style={{ margin: "2px 0 0 16px" }}>
                  {OPTION_LETTERS[oi]}. <InlineMath text={t(option)} />
                </p>
              ))}
            </div>
          ))}
          <h3>{t(HEADINGS.answerKey)}</h3>
          {quiz.map((q, i) => (
            <div
              key={i}
              className="export-item"
              style={{ display: "flex", gap: "6px", marginBottom: "6px" }}
            >
              <strong>
                {i + 1}. {OPTION_LETTERS[q.correct_index]}
              </strong>
              <CitedAnswer
                answer={t(q.option_explanations[q.correct_index] ?? "")}
                seekUrl={seekUrl}
              />
            </div>
          ))}
        </section>
      )}

      {bundle.notes.length > 0 && (
        <section>
          <h2>{t(HEADINGS.notes)}</h2>
          {bundle.notes.map((note) => (
            <div
              key={note.id}
              className="export-item"
              style={{ marginBottom: "12px" }}
            >
              <p style={{ margin: 0 }}>
                <span style={chipStyle}>{NOTE_KIND_LABELS[note.kind]}</span>{" "}
                {note.title && (
                  <strong>
                    <InlineMath text={t(note.title)} />
                  </strong>
                )}
                {stamp(note.timestamp_seconds)}
              </p>
              {note.body && (
                <CitedAnswer answer={t(note.body)} seekUrl={seekUrl} />
              )}
            </div>
          ))}
        </section>
      )}
    </>
  );
}

/**
 * Task 18: A print-ready copy of the lecture's summary, cheat sheet, flashcards, quiz and
 * notes in the chosen language. The browser's "Save as PDF" turns it into the PDF, which keeps
 * KaTeX math and Indian scripts sharp at no cost.
 */
export default function ExportPage() {
  const language = useLanguagePreference();
  const [state, setState] = useState<LoadState>({ status: "loading" });

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const lectureId = params.get("lecture") ?? "";
    let cancelled = false;
    Promise.resolve()
      .then(() => {
        if (!lectureId)
          throw new Error(
            "No lecture chosen. Open this page with the workspace's Export PDF button.",
          );
        return apiFetch<ExportBundle>(
          `/lectures/${encodeURIComponent(lectureId)}/export`,
        );
      })
      .then((bundle) => {
        if (cancelled) return;
        setState({
          status: "ready",
          bundle,
          autoPrint: params.get("print") === "1",
          exportedAt: new Date().toLocaleDateString(undefined, {
            day: "numeric",
            month: "long",
            year: "numeric",
          }),
        });
      })
      .catch((err) => {
        if (!cancelled)
          setState({ status: "error", message: errorMessage(err) });
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const backHref =
    state.status === "ready"
      ? `/chat?lecture=${state.bundle.lecture.id}`
      : "/chat";

  return (
    <LanguageContext.Provider value={language}>
      <style>{EXPORT_CSS}</style>
      <div
        className="no-print vp-container"
        style={{ maxWidth: "896px", paddingBlock: "28px 20px" }}
      >
        <div
          className="vp-card flex flex-wrap items-center justify-between gap-3 p-3 sm:p-4"
          style={{ borderRadius: "18px" }}
        >
          <Link href={backHref} className="vp-btn vp-btn-ghost vp-btn-sm">
            <Icon name="arrowLeft" />
            Back to the workspace
          </Link>
          <div className="flex flex-wrap items-center gap-3">
            <LanguageSelect />
            <button
              type="button"
              onClick={() => window.print()}
              disabled={state.status !== "ready"}
              className="vp-btn vp-btn-primary"
            >
              <Icon name="pdf" />
              Save as PDF
            </button>
          </div>
        </div>
        <p className="mt-3 text-center text-sm text-muted">
          In the print dialog, pick “Save as PDF” as the destination.
        </p>
      </div>

      {/* .vp-paper switches the design tokens to dark-on-white for the printed page */}
      <article
        className="export-sheet vp-paper"
        style={{
          maxWidth: "800px",
          margin: "0 auto 56px",
          padding: "clamp(24px, 5vw, 48px)",
          backgroundColor: "#fff",
          color: "var(--vp-text)",
          lineHeight: 1.55,
          fontFamily: "var(--font-sans)",
          boxShadow: "0 30px 80px -30px rgba(0, 0, 0, 0.9)",
          borderRadius: "12px",
        }}
      >
        {state.status === "loading" && <p style={mutedText}>Loading…</p>}
        {state.status === "error" && <p style={errorText}>{state.message}</p>}
        {state.status === "ready" && (
          <ExportDocument
            bundle={state.bundle}
            autoPrint={state.autoPrint}
            exportedAt={state.exportedAt}
          />
        )}
      </article>
    </LanguageContext.Provider>
  );
}
