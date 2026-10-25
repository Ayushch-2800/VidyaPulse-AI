"use client";

import {
  LANGUAGES,
  setLanguage,
  useLanguagePreference,
  type LanguageCode,
} from "@/lib/translate";

/** Picks the language the workspace translates generated content and notes into. */
export default function LanguageSelect() {
  const language = useLanguagePreference();
  return (
    <label style={{ display: "flex", alignItems: "center", gap: "8px" }}>
      <span style={{ fontSize: "0.9em", color: "var(--vp-text-2)" }}>
        Language
      </span>
      <select
        value={language}
        onChange={(e) => setLanguage(e.target.value as LanguageCode)}
        className="vp-input"
        style={{ width: "auto", minHeight: "44px", paddingBlock: "8px" }}
      >
        {LANGUAGES.map((l) => (
          <option key={l.code} value={l.code}>
            {l.label}
          </option>
        ))}
      </select>
    </label>
  );
}
