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
      <span style={{ fontSize: "0.9em" }}>Language</span>
      <select
        value={language}
        onChange={(e) => setLanguage(e.target.value as LanguageCode)}
        style={{
          padding: "8px 10px",
          borderRadius: "6px",
          border: "1px solid #ccc",
          backgroundColor: "#fff",
          color: "#111827",
        }}
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
