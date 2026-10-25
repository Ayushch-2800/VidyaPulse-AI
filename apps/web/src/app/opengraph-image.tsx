import { ImageResponse } from "next/og";

import { BRAND_GRADIENT, PulseMark } from "@/components/site/brand";

export const alt =
  "VidyaPulse AI: stop rewinding lectures, start mastering them";
export const size = { width: 1200, height: 630 };
export const contentType = "image/png";

export default function OpenGraphImage() {
  return new ImageResponse(
    <div
      style={{
        width: "100%",
        height: "100%",
        display: "flex",
        flexDirection: "column",
        justifyContent: "space-between",
        padding: "72px",
        color: "#f5f3ff",
        background:
          "radial-gradient(circle at 15% 0%, #4c1d95 0%, rgba(76,29,149,0) 55%), radial-gradient(circle at 100% 100%, #9d174d 0%, rgba(157,23,77,0) 50%), #07051a",
      }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: "20px" }}>
        <div
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            width: "84px",
            height: "84px",
            borderRadius: "24px",
            background: BRAND_GRADIENT,
          }}
        >
          <PulseMark size={72} />
        </div>
        <div style={{ display: "flex", fontSize: "44px", fontWeight: 800 }}>
          VidyaPulse AI
        </div>
      </div>
      <div style={{ display: "flex", flexDirection: "column" }}>
        <div
          style={{
            display: "flex",
            fontSize: "76px",
            fontWeight: 800,
            lineHeight: 1.05,
            letterSpacing: "-0.03em",
          }}
        >
          Stop rewinding lectures.
        </div>
        <div
          style={{
            display: "flex",
            fontSize: "76px",
            fontWeight: 800,
            lineHeight: 1.05,
            letterSpacing: "-0.03em",
            backgroundImage:
              "linear-gradient(90deg, #a78bfa, #f472b6, #fbbf24)",
            backgroundClip: "text",
            color: "transparent",
          }}
        >
          Start mastering them.
        </div>
        <div
          style={{
            display: "flex",
            marginTop: "28px",
            fontSize: "30px",
            color: "#d4d0f5",
          }}
        >
          Cited answers, cheat sheets, flashcards and quizzes from any lecture,
          in six languages.
        </div>
      </div>
    </div>,
    size,
  );
}
