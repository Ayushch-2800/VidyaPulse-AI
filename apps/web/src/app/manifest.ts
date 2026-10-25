import type { MetadataRoute } from "next";

export default function manifest(): MetadataRoute.Manifest {
  return {
    name: "VidyaPulse AI",
    short_name: "VidyaPulse",
    description:
      "Turn any lecture into cited answers, summaries, cheat sheets, flashcards and quizzes.",
    start_url: "/",
    display: "standalone",
    background_color: "#07051a",
    theme_color: "#07051a",
    icons: [{ src: "/icon.svg", sizes: "any", type: "image/svg+xml" }],
  };
}
