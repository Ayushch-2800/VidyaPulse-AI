"use client";

import { useState } from "react";

import { languageLabel, type Translation } from "@/lib/translate";
import { useElapsedSeconds } from "@/lib/workspace";

import { mutedText, secondaryButton } from "./styles";

const noteStyle: React.CSSProperties = {
  display: "flex",
  alignItems: "center",
  gap: "10px",
  flexWrap: "wrap",
  margin: "0 0 12px",
  padding: "10px 12px",
  borderRadius: "12px",
  border: "1px solid var(--vp-border)",
  backgroundColor: "var(--vp-surface-2)",
  fontSize: "0.9em",
  ...mutedText,
};

/**
 * Shows `children` only in the chosen language: while the translation loads it shows a
 * progress line in their place, so English and the chosen language are never mixed. If the
 * translation can't be loaded, a short notice says so and the content shows in English.
 * Without children it is just the notice.
 */
export default function TranslationNote({
  translation,
  children,
}: {
  translation: Translation;
  children?: React.ReactNode;
}) {
  const { translating, error, language, retry } = translation;
  if (translating) return <Translating key={language} language={language} />;
  return (
    <>
      {error && (
        <p role="status" style={noteStyle}>
          <span>{error}</span>
          <button type="button" onClick={retry} style={secondaryButton}>
            Try again
          </button>
        </p>
      )}
      {children}
    </>
  );
}

function Translating({ language }: { language: Translation["language"] }) {
  // Mounted when the translation starts, so this is its start time
  const [since] = useState(() => Date.now());
  const elapsed = useElapsedSeconds(since);
  return (
    <p role="status" style={noteStyle}>
      <span className="vp-spinner" aria-hidden="true" />
      <span>
        Translating into {languageLabel(language)}
        {elapsed ? ` · ${elapsed}s` : ""}. The first time takes a few seconds;
        after that it opens instantly.
      </span>
    </p>
  );
}
