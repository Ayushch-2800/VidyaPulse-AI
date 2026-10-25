"use client";

import { useEffect, useRef, useState } from "react";

import { INTRO_SEEN_KEY } from "./intro";
import { LogoMark } from "./Logo";

const WORD = "VidyaPulse";
// Matches the CSS: the wipe starts at 1.9 s and lasts 0.6 s
const DURATION_MS = 2500;
const SKIP_FADE_MS = 250;

/**
 * The short animated intro on the landing page, played once per browser tab session.
 * The animation and its exit are pure CSS, so it also leaves without JavaScript; this
 * component remembers that it played and lets any click or key skip it.
 */
export default function SplashScreen() {
  const [state, setState] = useState<"playing" | "leaving" | "done">("playing");
  const finished = useRef(false);

  useEffect(() => {
    const root = document.documentElement;
    if (root.dataset.intro === "seen") return;
    try {
      window.sessionStorage.setItem(INTRO_SEEN_KEY, "1");
    } catch {
      // Storage blocked: the intro just plays again next time
    }

    const stopListening = () => {
      window.removeEventListener("keydown", skip);
      window.removeEventListener("pointerdown", skip);
    };
    const finish = () => {
      if (finished.current) return;
      finished.current = true;
      stopListening();
      root.dataset.intro = "seen";
      setState("done");
    };
    function skip() {
      if (finished.current) return;
      stopListening();
      setState("leaving");
      window.setTimeout(finish, SKIP_FADE_MS);
    }

    const timer = window.setTimeout(finish, DURATION_MS);
    window.addEventListener("keydown", skip);
    window.addEventListener("pointerdown", skip);
    return () => {
      window.clearTimeout(timer);
      stopListening();
    };
  }, []);

  if (state === "done") return null;

  return (
    <div
      className="vp-splash"
      data-leaving={state === "leaving"}
      aria-hidden="true"
    >
      <div className="vp-splash__inner">
        <div className="vp-splash__mark">
          <span className="vp-splash__ring" />
          <span className="vp-splash__ring" />
          <LogoMark id="splash" />
        </div>
        <p className="vp-splash__word">
          {[...WORD].map((letter, i) => (
            <span key={i} style={{ "--i": i } as React.CSSProperties}>
              {letter}
            </span>
          ))}
          <span
            className="vp-splash__ai"
            style={{ "--i": WORD.length + 1 } as React.CSSProperties}
          >
            AI
          </span>
        </p>
        <p className="vp-splash__tagline">Every lecture. Decoded.</p>
        <div className="vp-splash__bar" />
      </div>
      <span className="vp-splash__skip">Tap or press any key to skip</span>
    </div>
  );
}
