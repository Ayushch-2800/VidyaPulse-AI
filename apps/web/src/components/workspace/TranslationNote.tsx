"use client";

import { useState } from "react";

import { languageLabel, type Translation } from "@/lib/translate";
import { useElapsedSeconds } from "@/lib/workspace";

import { errorText, mutedText } from "./styles";

/** Says when content is being translated, or that the translation failed. */
export default function TranslationNote({
  translation,
}: {
  translation: Translation;
}) {
  const { translating, error, language } = translation;
  if (error) {
    return (
      <p style={{ margin: "0 0 12px", fontSize: "0.85em", ...errorText }}>
        Could not translate into {languageLabel(language)}, so this is the
        original. {error}
      </p>
    );
  }
  if (!translating) return null;
  return <Translating key={language} language={language} />;
}

function Translating({ language }: { language: Translation["language"] }) {
  // Mounted when the translation starts, so this is its start time
  const [since] = useState(() => Date.now());
  const elapsed = useElapsedSeconds(since);
  return (
    <p
      role="status"
      style={{
        display: "flex",
        alignItems: "center",
        gap: "10px",
        margin: "0 0 12px",
        padding: "10px 12px",
        borderRadius: "12px",
        border: "1px solid var(--vp-border)",
        backgroundColor: "var(--vp-surface-2)",
        fontSize: "0.9em",
        ...mutedText,
      }}
    >
      <span className="vp-spinner" aria-hidden="true" />
      <span>
        Translating into {languageLabel(language)}
        {elapsed ? ` · ${elapsed}s` : ""}. Showing English until it&apos;s
        ready. The first time takes a few seconds; after that it opens
        instantly.
      </span>
    </p>
  );
}
