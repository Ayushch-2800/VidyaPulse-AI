import {
  createContext,
  useContext,
  useEffect,
  useReducer,
  useState,
  useSyncExternalStore,
} from "react";

import { apiFetch, errorMessage } from "@/lib/workspace";

// Must match LANGUAGES in apps/server/translator.py
export const LANGUAGES = [
  { code: "en", label: "English" },
  { code: "hi", label: "हिन्दी · Hindi" },
  { code: "ta", label: "தமிழ் · Tamil" },
  { code: "te", label: "తెలుగు · Telugu" },
  { code: "mr", label: "मराठी · Marathi" },
  { code: "bn", label: "বাংলা · Bengali" },
] as const;

export type LanguageCode = (typeof LANGUAGES)[number]["code"];

const SOURCE_LANGUAGE: LanguageCode = "en";
const STORAGE_KEY = "vidyapulse-language";
// The backend accepts at most 300 texts per request
const MAX_TEXTS_PER_REQUEST = 250;

function isLanguage(value: unknown): value is LanguageCode {
  return LANGUAGES.some((l) => l.code === value);
}

export function languageLabel(code: LanguageCode): string {
  return LANGUAGES.find((l) => l.code === code)?.label ?? code;
}

// ---- The chosen language, remembered in this browser and shared by every open tab ----

let chosenLanguage: LanguageCode | null = null;
const languageListeners = new Set<() => void>();

function readLanguage(): LanguageCode {
  if (chosenLanguage) return chosenLanguage;
  try {
    const saved = window.localStorage.getItem(STORAGE_KEY);
    if (isLanguage(saved)) return saved;
  } catch {
    // Storage blocked (private window): fall back to English
  }
  return SOURCE_LANGUAGE;
}

function subscribeLanguage(listener: () => void) {
  const onStorage = (e: StorageEvent) => {
    if (e.key !== STORAGE_KEY) return;
    chosenLanguage = null;
    listener();
  };
  languageListeners.add(listener);
  window.addEventListener("storage", onStorage);
  return () => {
    languageListeners.delete(listener);
    window.removeEventListener("storage", onStorage);
  };
}

export function setLanguage(code: LanguageCode) {
  chosenLanguage = code;
  try {
    window.localStorage.setItem(STORAGE_KEY, code);
  } catch {
    // Still applies to this tab
  }
  languageListeners.forEach((listener) => listener());
}

/** The language picked in the workspace's language switch (English on the server render). */
export function useLanguagePreference(): LanguageCode {
  return useSyncExternalStore(
    subscribeLanguage,
    readLanguage,
    () => SOURCE_LANGUAGE,
  );
}

export const LanguageContext = createContext<LanguageCode>(SOURCE_LANGUAGE);

// ---- Translations, cached in this browser (the backend also caches them in Supabase) ----

const translations = new Map<string, string>();
const inflight = new Map<string, Promise<void>>();
// Kept in localStorage so a language opens instantly on later visits, up to about this many
// characters; the oldest translations are dropped first
const TRANSLATIONS_KEY = "vidyapulse-translations";
const MAX_SAVED_CHARS = 1_500_000;
let restored = false;
let saveTimer: number | undefined;

function cacheKey(language: string, text: string): string {
  return `${language}\u0000${text}`;
}

function restoreTranslations() {
  if (restored || typeof window === "undefined") return;
  restored = true;
  try {
    const saved = window.localStorage.getItem(TRANSLATIONS_KEY);
    if (!saved) return;
    for (const [key, value] of JSON.parse(saved) as [string, string][]) {
      if (!translations.has(key)) translations.set(key, value);
    }
  } catch {
    // Unreadable or blocked: translations load from the backend instead
  }
}

function saveTranslations() {
  window.clearTimeout(saveTimer);
  saveTimer = window.setTimeout(() => {
    const entries = [...translations];
    let size = entries.reduce((n, [k, v]) => n + k.length + v.length, 0);
    let drop = 0;
    while (size > MAX_SAVED_CHARS && drop < entries.length) {
      size -= entries[drop][0].length + entries[drop][1].length;
      drop++;
    }
    try {
      window.localStorage.setItem(
        TRANSLATIONS_KEY,
        JSON.stringify(entries.slice(drop)),
      );
    } catch {
      // Storage full or blocked: still cached for this visit
    }
  }, 1000);
}

async function fetchTranslations(language: LanguageCode, texts: string[]) {
  for (let start = 0; start < texts.length; start += MAX_TEXTS_PER_REQUEST) {
    const batch = texts.slice(start, start + MAX_TEXTS_PER_REQUEST);
    const data = await apiFetch<{ translations: string[] }>("/translate", {
      method: "POST",
      body: JSON.stringify({ texts: batch, language }),
    });
    data.translations.forEach((translated, i) =>
      translations.set(cacheKey(language, batch[i]), translated),
    );
  }
  saveTranslations();
}

/** One request per distinct set of texts, however many components ask for it at once. */
function requestTranslations(language: LanguageCode, texts: string[]) {
  const key = cacheKey(language, JSON.stringify(texts));
  let request = inflight.get(key);
  if (!request) {
    request = fetchTranslations(language, texts).finally(() =>
      inflight.delete(key),
    );
    inflight.set(key, request);
  }
  return request;
}

export type Translation = {
  /** The text in the chosen language, or the original until its translation arrives. */
  t: (text: string) => string;
  language: LanguageCode;
  translating: boolean;
  error: string | null;
};

/**
 * Translates `texts` into the language from LanguageContext. Pass every text the component
 * shows; render each through t(). Pass enabled=false while the component is hidden so no
 * Gemini call is spent on it.
 */
export function useTranslation(texts: string[], enabled = true): Translation {
  const language = useContext(LanguageContext);
  restoreTranslations();
  const [, rerender] = useReducer((n: number) => n + 1, 0);
  const [failure, setFailure] = useState<{
    key: string;
    message: string;
  } | null>(null);

  const missing =
    language === SOURCE_LANGUAGE || !enabled
      ? []
      : [...new Set(texts)].filter(
          (text) => text.trim() && !translations.has(cacheKey(language, text)),
        );
  const requestKey = missing.length
    ? JSON.stringify({ language, texts: missing })
    : "";

  useEffect(() => {
    if (!requestKey) return;
    const request = JSON.parse(requestKey) as {
      language: LanguageCode;
      texts: string[];
    };
    let cancelled = false;
    requestTranslations(request.language, request.texts).then(
      () => {
        if (!cancelled) rerender();
      },
      (err) => {
        if (!cancelled)
          setFailure({ key: requestKey, message: errorMessage(err) });
      },
    );
    return () => {
      cancelled = true;
    };
  }, [requestKey]);

  const failed = failure !== null && failure.key === requestKey;
  return {
    t: (text: string) =>
      language === SOURCE_LANGUAGE
        ? text
        : (translations.get(cacheKey(language, text)) ?? text),
    language,
    translating: requestKey !== "" && !failed,
    error: failed ? failure.message : null,
  };
}
