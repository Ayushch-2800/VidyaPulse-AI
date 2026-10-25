import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Add a lecture",
  description:
    "Paste a YouTube lecture link and VidyaPulse AI transcribes it, reads the board and indexes it for questions and revision.",
};

export default function IngestLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return children;
}
