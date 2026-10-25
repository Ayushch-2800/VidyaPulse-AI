"use client";

import { languageLabel, type Translation } from "@/lib/translate";

import { errorText, mutedText } from "./styles";

/** Says when content is being translated, or that the translation failed. */
export default function TranslationNote({
  translation,
}: {
  translation: Translation;
}) {
  const { translating, error, language } = translation;
  if (!translating && !error) return null;
  return (
    <p
      style={{
        margin: "0 0 12px",
        fontSize: "0.85em",
        ...(error ? errorText : mutedText),
      }}
    >
      {error
        ? `Could not translate into ${languageLabel(language)}, so this is the original. ${error}`
        : `Translating into ${languageLabel(language)} with Gemini…`}
    </p>
  );
}
