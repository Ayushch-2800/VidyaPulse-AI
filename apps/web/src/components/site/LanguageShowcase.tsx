"use client";

import { useEffect, useState } from "react";

import { LANGUAGES, type LanguageCode } from "@/lib/translate";

// "This lecture, in your language." in every language the workspace offers
const PHRASES: Record<LanguageCode, string> = {
  en: "This lecture, in your language.",
  hi: "यह लेक्चर, आपकी भाषा में।",
  ta: "இந்த விரிவுரை, உங்கள் மொழியில்.",
  te: "ఈ ఉపన్యాసం, మీ భాషలో.",
  mr: "हे लेक्चर, तुमच्या भाषेत.",
  bn: "এই লেকচার, আপনার ভাষায়।",
};

const CYCLE_MS = 2800;

/** Cycles a sample line through the workspace languages; pauses on hover, focus or a pick. */
export default function LanguageShowcase() {
  const [index, setIndex] = useState(0);
  const [hovered, setHovered] = useState(false);
  const [picked, setPicked] = useState(false);

  useEffect(() => {
    if (hovered || picked) return;
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    const timer = window.setInterval(
      () => setIndex((i) => (i + 1) % LANGUAGES.length),
      CYCLE_MS,
    );
    return () => window.clearInterval(timer);
  }, [hovered, picked]);

  const language = LANGUAGES[index];

  return (
    <div
      className="vp-card vp-lang-card"
      onPointerEnter={() => setHovered(true)}
      onPointerLeave={() => setHovered(false)}
      onFocus={() => setHovered(true)}
      onBlur={() => setHovered(false)}
    >
      <div className="flex flex-wrap items-center justify-between gap-3">
        <span className="vp-eyebrow">Workspace language</span>
        <span className="vp-tag">{language.label}</span>
      </div>
      <div className="vp-lang-phrase">
        <p key={language.code} lang={language.code}>
          {PHRASES[language.code]}
        </p>
      </div>
      <div
        className="vp-lang-chips"
        role="group"
        aria-label="Preview the workspace in a language"
      >
        {LANGUAGES.map((l, i) => (
          <button
            key={l.code}
            type="button"
            className="vp-lang-chip"
            lang={l.code}
            aria-pressed={i === index}
            onClick={() => {
              setIndex(i);
              setPicked(true);
            }}
          >
            {l.label}
          </button>
        ))}
      </div>
    </div>
  );
}
