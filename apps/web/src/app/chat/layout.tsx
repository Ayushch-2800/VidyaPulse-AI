import type { Metadata } from "next";

// Covers the workspace and its PDF export; both show a signed-in student's own lectures
export const metadata: Metadata = {
  title: "Lecture workspace",
  description:
    "Ask doubts, read the summary, revise with cheat sheets, flashcards and quizzes, and export your notes.",
  robots: { index: false },
};

export default function ChatLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return children;
}
