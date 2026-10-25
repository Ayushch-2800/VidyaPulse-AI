import Link from "next/link";

import Icon, { type IconName } from "@/components/site/Icon";
import LanguageShowcase from "@/components/site/LanguageShowcase";
import SplashScreen from "@/components/site/SplashScreen";
import SpotlightGroup from "@/components/site/SpotlightGroup";

type CSSVars = React.CSSProperties & Record<`--${string}`, string | number>;

const delay = (seconds: number): CSSVars => ({ "--d": `${seconds}s` });

const MARQUEE = [
  "JEE",
  "NEET",
  "GATE",
  "UPSC",
  "Physics",
  "Chemistry",
  "Mathematics",
  "Biology",
  "Engineering",
  "Hinglish",
  "हिन्दी",
  "தமிழ்",
  "తెలుగు",
  "मराठी",
  "বাংলা",
];

const STATS = [
  { value: "6", label: "languages to study in" },
  { value: "4", label: "ways to revise every lecture" },
  { value: "▶ MM:SS", label: "on every cited answer" },
  { value: "1 click", label: "to a print-ready PDF" },
];

const STEPS: { icon: IconName; title: string; body: string }[] = [
  {
    icon: "video",
    title: "Bring any lecture",
    body: "Paste a YouTube link, upload a recording, or capture a live class with the VidyaPulse Chrome extension.",
  },
  {
    icon: "sparkles",
    title: "VidyaPulse listens and reads",
    body: "Speech in English, Hindi or Hinglish is transcribed, the board is read with OCR, and everything is indexed to the second.",
  },
  {
    icon: "zap",
    title: "Study like a topper",
    body: "Ask doubts, revise with cheat sheets, flashcards and quizzes, and export your notes before the exam.",
  },
];

const FAQ = [
  {
    q: "Which lectures can I use?",
    a: "Any YouTube lecture link, an audio or video recording you upload (MP3, MP4, MKV or WAV), or a class you capture live with the Chrome extension.",
  },
  {
    q: "Will the answers make things up?",
    a: "Answers are built from the lecture itself and cite the moments they come from. When the lecture doesn't cover something, VidyaPulse says so instead of guessing.",
  },
  {
    q: "Which languages are supported?",
    a: "You can study in English, Hindi, Tamil, Telugu, Marathi and Bengali. Lectures spoken in English, Hindi or a mix of both are transcribed.",
  },
  {
    q: "Can I take my notes offline?",
    a: "Yes. Export PDF bundles the summary, cheat sheet, flashcards, quiz with its answer key and your own notes into one print-ready document, with timestamps that link back to the video.",
  },
  {
    q: "Are my lectures private?",
    a: "Lectures are tied to your account and kept in private storage, and the workspace only lists the lectures you own.",
  },
];

// Bar heights for the waveform in the preview, fixed so server and client agree
const WAVE = Array.from(
  { length: 40 },
  (_, i) =>
    28 + Math.round(64 * Math.abs(Math.sin(i * 0.7) * Math.cos(i * 0.23))),
);

function HeroPreview() {
  return (
    <div
      className="vp-demo vp-enter"
      style={delay(0.35)}
      role="img"
      aria-label="Preview of the VidyaPulse workspace: a physics lecture playing beside a question and an answer that cites two timestamps"
    >
      <div className="vp-demo__glow" />
      <div className="vp-demo__window" aria-hidden="true">
        <div className="vp-demo__bar">
          <i />
          <i />
          <i />
          <span>Lecture workspace</span>
        </div>
        <div className="vp-demo__body">
          <div className="vp-demo__video">
            <div className="vp-demo__board">
              <small>Physics · Electrostatics · Lecture 7</small>∮ E · dA = Q
              <sub>enc</sub> / ε₀
            </div>
            <div className="vp-demo__play">
              <Icon name="play" />
            </div>
            <div className="vp-wave">
              {WAVE.map((h, i) => (
                <span key={i} style={{ "--h": `${h}%`, "--i": i } as CSSVars} />
              ))}
            </div>
            <div className="vp-demo__progress" />
          </div>
          <div className="vp-demo__chat">
            <div className="vp-demo__q">
              Why is the field zero inside a charged shell?
            </div>
            <div className="vp-demo__typing">
              <i />
              <i />
              <i />
            </div>
            <div className="vp-demo__a">
              <p>
                All the charge sits on the outer surface, so a Gaussian surface
                inside encloses none. By Gauss&apos;s law the flux, and so the
                field, is zero.
              </p>
              <span className="vp-seek">▶ 14:32</span>
              <span className="vp-seek">▶ 18:05</span>
            </div>
          </div>
        </div>
      </div>
      <div className="vp-float vp-float--sheet" aria-hidden="true">
        <Icon name="checkCircle" />
        Cheat sheet ready
      </div>
      <div className="vp-float vp-float--quiz" aria-hidden="true">
        <Icon name="quiz" />
        Quiz score 9 / 10
      </div>
      <div className="vp-float vp-float--lang" aria-hidden="true">
        <Icon name="languages" />
        हिन्दी · தமிழ் · বাংলা
      </div>
    </div>
  );
}

function Hero() {
  return (
    <section className="vp-hero" aria-labelledby="hero-title">
      <div className="vp-container grid items-center gap-16 lg:grid-cols-[1.08fr_1fr]">
        <div>
          <p className="vp-pill vp-enter">
            <span className="vp-pill__tag">AI</span>
            Lecture intelligence for Indian classrooms
          </p>
          <h1
            id="hero-title"
            className="vp-hero__title vp-enter"
            style={delay(0.1)}
          >
            Stop rewinding lectures.{" "}
            <span className="vp-gradient-text">Start mastering them.</span>
          </h1>
          <p className="vp-lead max-w-xl vp-enter" style={delay(0.2)}>
            VidyaPulse AI turns any lecture into answers you can trust, each one
            linked to the second it was taught, plus summaries, cheat sheets,
            flashcards and quizzes in your language.
          </p>
          <div
            className="mt-9 flex flex-wrap gap-3 vp-enter"
            style={delay(0.3)}
          >
            <Link href="/chat" className="vp-btn vp-btn-primary vp-btn-lg">
              Open your workspace
              <Icon name="arrowRight" />
            </Link>
            <Link href="/ingest" className="vp-btn vp-btn-ghost vp-btn-lg">
              <Icon name="play" />
              Add a lecture
            </Link>
          </div>
          <ul className="vp-check-list mt-9 vp-enter" style={delay(0.4)}>
            <li>
              <Icon name="check" />
              English, Hindi and Hinglish audio
            </li>
            <li>
              <Icon name="check" />
              Timestamps on every answer
            </li>
            <li>
              <Icon name="check" />
              One-click PDF notes
            </li>
          </ul>
        </div>
        <HeroPreview />
      </div>
    </section>
  );
}

function Marquee() {
  const group = (hidden: boolean) => (
    <ul className="vp-marquee__group" aria-hidden={hidden || undefined}>
      {MARQUEE.map((item) => (
        <li key={item}>{item}</li>
      ))}
    </ul>
  );
  return (
    <div className="vp-marquee" aria-label="Exams, subjects and languages">
      {/* Two copies, so moving left by half loops without a seam */}
      <div className="vp-marquee__track">
        {group(false)}
        {group(true)}
      </div>
    </div>
  );
}

function Stats() {
  return (
    <section className="vp-container mt-16" aria-label="VidyaPulse at a glance">
      <div className="vp-stats vp-reveal">
        {STATS.map((stat) => (
          <div key={stat.label} className="vp-stat">
            <span className="vp-stat__value vp-gradient-text">
              {stat.value}
            </span>
            <span className="vp-stat__label">{stat.label}</span>
          </div>
        ))}
      </div>
    </section>
  );
}

function FeatureCard({
  icon,
  title,
  body,
  className = "",
  children,
}: {
  icon: IconName;
  title: string;
  body: string;
  className?: string;
  children?: React.ReactNode;
}) {
  return (
    <article className={`vp-card vp-feature vp-reveal ${className}`}>
      <div className="vp-icon-tile">
        <Icon name={icon} />
      </div>
      <h3>{title}</h3>
      <p>{body}</p>
      {children && (
        <div className="vp-feature__visual" aria-hidden="true">
          {children}
        </div>
      )}
    </article>
  );
}

function Features() {
  return (
    <section
      id="features"
      className="vp-section"
      aria-labelledby="features-title"
    >
      <div className="vp-container">
        <div className="vp-section-head vp-reveal">
          <p className="vp-eyebrow">Everything in one workspace</p>
          <h2 id="features-title" className="vp-section-title">
            One lecture in.{" "}
            <span className="vp-gradient-text">A complete study kit out.</span>
          </h2>
          <p className="vp-lead">
            VidyaPulse reads every word, slide and formula, then builds what you
            need to understand it, revise it and remember it.
          </p>
        </div>

        <SpotlightGroup className="vp-bento">
          <FeatureCard
            icon="ask"
            title="Ask doubts, get answers with proof"
            body="Every answer comes from the lecture and cites the moment it was taught. Tap a timestamp and the video jumps right there."
            className="is-wide"
          >
            <div className="grid gap-3">
              <div className="vp-demo__q" style={{ animation: "none" }}>
                What&apos;s the difference between speed and velocity?
              </div>
              <div className="vp-demo__a" style={{ animation: "none" }}>
                <p>
                  Speed is how fast something moves. Velocity also has a
                  direction, so it is a vector.
                </p>
                <span className="vp-seek">▶ 03:12</span>
                <span className="vp-seek">▶ 05:47</span>
              </div>
              <div className="vp-ask-bar">
                Ask a question about this lecture…
                <span className="vp-ask-bar__send">
                  <Icon name="arrowRight" />
                </span>
              </div>
            </div>
          </FeatureCard>

          <FeatureCard
            icon="transcript"
            title="A transcript that keeps up"
            body="The transcript follows the video line by line. Click any line to jump to it."
          >
            {[
              ["12:04", "So the net charge enclosed is zero…"],
              ["12:09", "which means the flux through it is zero."],
              ["12:15", "Now let's take a point outside the shell."],
            ].map(([time, line], i) => (
              <span
                key={time}
                className="vp-transcript-line"
                style={{ "--i": i } as CSSVars}
              >
                <b>{time}</b>
                {line}
              </span>
            ))}
          </FeatureCard>

          <FeatureCard
            icon="formula"
            title="Cheat sheets that speak exam"
            body="Definitions, theorems and formulas in clean math, tagged with the JEE, NEET, GATE and UPSC topics they map to."
          >
            <p className="vp-formula">v² = u² + 2as</p>
            <div className="mt-3 flex flex-wrap justify-center gap-1.5">
              <span className="vp-tag">JEE · Kinematics</span>
              <span className="vp-tag">NEET · Motion</span>
            </div>
          </FeatureCard>

          <FeatureCard
            icon="cards"
            title="Flashcards and quizzes that teach back"
            body="Active-recall cards, and quizzes that explain why each option is right or wrong."
          >
            <div className="vp-flip">
              <div className="vp-flip__inner">
                <div className="vp-flip__face">
                  <small>Question</small>
                  SI unit of electric flux?
                </div>
                <div className="vp-flip__face vp-flip__face--back">
                  <small>Answer</small>
                  <strong>N·m²/C</strong>
                </div>
              </div>
            </div>
          </FeatureCard>

          <FeatureCard
            icon="scan"
            title="Reads the board, too"
            body="Slides and board work are read with OCR and searched with the speech, so diagram-heavy lectures still make sense."
          >
            <div className="vp-scan">
              F = ma
              <br />
              p = mv
              <br />W = F · s · cos θ
            </div>
          </FeatureCard>

          <FeatureCard
            icon="pdf"
            title="Your notes, ready to print"
            body="Save any answer, flashcard or formula to your notes, add your own pinned to the moment, and export everything as one clean PDF in your language."
            className="is-wide is-full"
          >
            <div className="grid items-center gap-5 sm:grid-cols-[1fr_auto]">
              <div className="vp-doc">
                <span
                  style={{
                    width: "40%",
                    height: 12,
                    background: "rgba(196,181,253,.45)",
                  }}
                />
                <span style={{ width: "92%" }} />
                <span style={{ width: "86%" }} />
                <span style={{ width: "64%" }} />
                <span style={{ width: "78%" }} />
              </div>
              <div className="flex flex-wrap gap-2">
                <span className="vp-btn vp-btn-ghost vp-btn-sm">
                  ☆ Save to notes
                </span>
                <span className="vp-btn vp-btn-primary vp-btn-sm">
                  <Icon name="pdf" />
                  Export PDF
                </span>
              </div>
            </div>
          </FeatureCard>
        </SpotlightGroup>
      </div>
    </section>
  );
}

function HowItWorks() {
  return (
    <section
      id="how-it-works"
      className="vp-section"
      style={{ paddingTop: 0 }}
      aria-labelledby="how-title"
    >
      <div className="vp-container">
        <div className="vp-section-head vp-reveal">
          <p className="vp-eyebrow">How it works</p>
          <h2 id="how-title" className="vp-section-title">
            From lecture to revision in{" "}
            <span className="vp-gradient-text">three steps</span>
          </h2>
        </div>
        <ol className="vp-steps">
          {STEPS.map((step, i) => (
            <li key={step.title} className="vp-card vp-step vp-reveal">
              <div className="flex items-center justify-between">
                <span className="vp-step__num">0{i + 1}</span>
                <span className="vp-icon-tile">
                  <Icon name={step.icon} />
                </span>
              </div>
              <h3>{step.title}</h3>
              <p>{step.body}</p>
            </li>
          ))}
        </ol>
      </div>
    </section>
  );
}

function Languages() {
  return (
    <section
      id="languages"
      className="vp-section"
      style={{ paddingTop: 0 }}
      aria-labelledby="languages-title"
    >
      <div className="vp-container grid items-center gap-12 lg:grid-cols-2">
        <div className="vp-reveal">
          <p className="vp-eyebrow">Multilingual by design</p>
          <h2 id="languages-title" className="vp-section-title">
            Learn in the language{" "}
            <span className="vp-gradient-text">you think in.</span>
          </h2>
          <p className="vp-lead">
            Switch the whole workspace with one tap. Summaries, cheat sheets,
            flashcards, quizzes and your own notes are translated, and the PDF
            follows along.
          </p>
          <ul className="vp-check-list mt-8" style={{ display: "grid" }}>
            <li>
              <Icon name="check" />
              English, हिन्दी, தமிழ், తెలుగు, मराठी and বাংলা
            </li>
            <li>
              <Icon name="check" />
              Hinglish lectures understood the way they&apos;re spoken
            </li>
            <li>
              <Icon name="check" />
              Formulas and timestamps stay exactly as taught
            </li>
          </ul>
        </div>
        <div className="vp-reveal">
          <LanguageShowcase />
        </div>
      </div>
    </section>
  );
}

function Faq() {
  return (
    <section
      id="faq"
      className="vp-section"
      style={{ paddingTop: 0 }}
      aria-labelledby="faq-title"
    >
      <div className="vp-container grid gap-10 lg:grid-cols-[1fr_1.4fr]">
        <div className="vp-reveal">
          <p className="vp-eyebrow">FAQ</p>
          <h2 id="faq-title" className="vp-section-title">
            Questions, answered.
          </h2>
          <p className="vp-lead">
            Everything you need to know before your first lecture.
          </p>
        </div>
        <div className="vp-faq vp-reveal">
          {FAQ.map((item) => (
            <details key={item.q}>
              <summary>{item.q}</summary>
              <p>{item.a}</p>
            </details>
          ))}
        </div>
      </div>
    </section>
  );
}

function FinalCta() {
  return (
    <section className="vp-container pb-24" aria-labelledby="cta-title">
      <div className="vp-cta vp-reveal">
        <p className="vp-eyebrow relative">Your next lecture starts here</p>
        <h2
          id="cta-title"
          className="vp-section-title relative mx-auto"
          style={{ maxWidth: "780px" }}
        >
          Ready to turn lectures into{" "}
          <span className="vp-gradient-text">ranks?</span>
        </h2>
        <p className="vp-lead relative mx-auto max-w-xl">
          Open the workspace, pick a lecture and ask your first doubt. It takes
          less than a minute.
        </p>
        <div className="relative mt-9 flex flex-wrap justify-center gap-3">
          <Link href="/chat" className="vp-btn vp-btn-primary vp-btn-lg">
            Open your workspace
            <Icon name="arrowRight" />
          </Link>
          <Link href="/login" className="vp-btn vp-btn-ghost vp-btn-lg">
            <Icon name="logIn" />
            Log in or sign up
          </Link>
        </div>
      </div>
    </section>
  );
}

export default function Home() {
  return (
    <>
      <SplashScreen />
      <Hero />
      <Marquee />
      <Stats />
      <Features />
      <HowItWorks />
      <Languages />
      <Faq />
      <FinalCta />
    </>
  );
}
