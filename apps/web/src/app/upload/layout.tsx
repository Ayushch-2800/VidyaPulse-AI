import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Upload a recording",
  description: "Store a lecture recording in your private VidyaPulse storage.",
  robots: { index: false },
};

export default function UploadLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return children;
}
