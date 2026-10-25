"use client";

import Link from "next/link";
import { useRef, useState } from "react";

import Icon, { type IconName } from "@/components/site/Icon";
import { API_URL } from "@/lib/api";
import { createClient } from "@/lib/supabase/client";

type Tone = "info" | "success" | "error";

const PERKS: { icon: IconName; text: string }[] = [
  { icon: "ask", text: "Ask doubts and get answers that cite the lecture" },
  { icon: "cards", text: "Revise with cheat sheets, flashcards and quizzes" },
  { icon: "languages", text: "Study in English or five Indian languages" },
  { icon: "lock", text: "Your lectures and notes stay private to you" },
];

function errorText(err: unknown): string {
  return err instanceof Error ? err.message : String(err);
}

export default function LoginPage() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [message, setMessage] = useState("");
  const [tone, setTone] = useState<Tone>("info");
  const [busy, setBusy] = useState<"login" | "signup" | null>(null);
  const [token, setToken] = useState("");
  const form = useRef<HTMLFormElement>(null);

  const [supabase] = useState(createClient);

  const say = (text: string, nextTone: Tone) => {
    setMessage(text);
    setTone(nextTone);
  };

  const handleSignUp = async () => {
    // Same checks as logging in: a real email and a password Supabase accepts
    if (!form.current?.reportValidity()) return;
    setBusy("signup");
    try {
      const { error } = await supabase.auth.signUp({ email, password });
      if (error) say(`Error: ${error.message}`, "error");
      else
        say(
          "Sign up successful! Check your email or try logging in.",
          "success",
        );
    } catch (err) {
      say(`Error: ${errorText(err)}`, "error");
    } finally {
      setBusy(null);
    }
  };

  const handleLogIn = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy("login");
    try {
      const { data, error } = await supabase.auth.signInWithPassword({
        email,
        password,
      });
      if (error) {
        say(`Error: ${error.message}`, "error");
      } else {
        say("Login successful!", "success");
        setToken(data.session?.access_token || "");
      }
    } catch (err) {
      say(`Error: ${errorText(err)}`, "error");
    } finally {
      setBusy(null);
    }
  };

  const testProtectedBackend = async () => {
    if (!token) {
      say("Please log in first to get JWT token.", "error");
      return;
    }
    try {
      const res = await fetch(`${API_URL}/auth/me`, {
        headers: {
          Authorization: `Bearer ${token}`,
        },
      });
      const data = await res.json();
      say(`Backend Response: ${JSON.stringify(data)}`, "info");
    } catch (err) {
      say(`Fetch Error: ${errorText(err)}`, "error");
    }
  };

  return (
    <div className="vp-container vp-page">
      <div className="grid items-center gap-12 lg:grid-cols-[1fr_minmax(0,460px)] lg:gap-20">
        <div className="vp-enter">
          <p className="vp-eyebrow">Welcome to VidyaPulse</p>
          <h1
            className="vp-page-title"
            style={{ fontSize: "clamp(2.2rem, 4.6vw, 3.4rem)" }}
          >
            Log in and pick up{" "}
            <span className="vp-gradient-text">where you left off.</span>
          </h1>
          <p className="vp-lead mt-5 max-w-lg">
            Your lectures, answers, flashcards and notes are waiting for you.
          </p>
          <ul className="mt-9 grid gap-4">
            {PERKS.map((perk) => (
              <li key={perk.text} className="flex items-center gap-4">
                <span className="vp-icon-tile">
                  <Icon name={perk.icon} />
                </span>
                <span className="text-fg-2">{perk.text}</span>
              </li>
            ))}
          </ul>
        </div>

        <div
          className="vp-card vp-enter p-6 sm:p-8"
          style={{ "--d": "0.12s" } as React.CSSProperties}
        >
          <h2 className="font-display text-2xl font-bold">Log in or sign up</h2>
          <p className="mt-1 text-sm text-muted">
            Use your email and a password of at least 6 characters.
          </p>

          <form ref={form} onSubmit={handleLogIn} className="mt-6 grid gap-4">
            <div>
              <label htmlFor="email" className="vp-label">
                Email
              </label>
              <input
                id="email"
                type="email"
                required
                autoComplete="email"
                placeholder="you@example.com"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                className="vp-input"
              />
            </div>
            <div>
              <label htmlFor="password" className="vp-label">
                Password
              </label>
              <div className="relative">
                <input
                  id="password"
                  type={showPassword ? "text" : "password"}
                  required
                  minLength={6}
                  autoComplete="current-password"
                  placeholder="At least 6 characters"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  className="vp-input pr-12"
                />
                <button
                  type="button"
                  onClick={() => setShowPassword((v) => !v)}
                  aria-label={showPassword ? "Hide password" : "Show password"}
                  className="absolute top-1/2 right-1.5 grid h-9 w-9 -translate-y-1/2 cursor-pointer place-items-center rounded-lg text-muted transition-colors hover:text-fg"
                >
                  <Icon
                    name={showPassword ? "eyeOff" : "eye"}
                    className="h-5 w-5"
                  />
                </button>
              </div>
            </div>
            <button
              type="submit"
              disabled={busy !== null}
              className="vp-btn vp-btn-primary vp-btn-lg mt-2 w-full"
            >
              {busy === "login" ? (
                <span className="vp-spinner" aria-hidden="true" />
              ) : (
                <Icon name="logIn" />
              )}
              {busy === "login" ? "Logging in…" : "Log in"}
            </button>
            <button
              type="button"
              onClick={handleSignUp}
              disabled={busy !== null}
              className="vp-btn vp-btn-ghost w-full"
            >
              {busy === "signup" && (
                <span className="vp-spinner" aria-hidden="true" />
              )}
              {busy === "signup" ? "Creating account…" : "Create a new account"}
            </button>
          </form>

          <div role="status" aria-live="polite">
            {message && (
              <p className="vp-status mt-5" data-tone={tone}>
                {message}
              </p>
            )}
          </div>

          {token && (
            <Link href="/chat" className="vp-btn vp-btn-primary mt-4 w-full">
              Open your workspace
              <Icon name="arrowRight" />
            </Link>
          )}

          <details className="mt-6 border-t border-line pt-4 text-sm">
            <summary className="cursor-pointer text-muted">
              Developer check
            </summary>
            <p className="mt-2 text-muted">
              Calls the FastAPI <code>/auth/me</code> route with your session
              token.
            </p>
            <button
              type="button"
              onClick={testProtectedBackend}
              className="vp-btn vp-btn-ghost vp-btn-sm mt-3"
            >
              Test FastAPI /auth/me
            </button>
          </details>
        </div>
      </div>
    </div>
  );
}
