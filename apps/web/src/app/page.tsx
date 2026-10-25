import Link from "next/link";

const pages = [
  { href: "/login", label: "Log in", note: "Sign up or log in with Supabase" },
  {
    href: "/chat",
    label: "Lecture workspace",
    note: "Ask, summarize, revise with flashcards and quizzes, take notes and export a PDF",
  },
  {
    href: "/ingest",
    label: "Ingest a lecture",
    note: "Process a YouTube lecture",
  },
  {
    href: "/upload",
    label: "Upload a file",
    note: "Test Supabase storage uploads",
  },
];

export default function Home() {
  return (
    <div
      style={{
        maxWidth: "600px",
        margin: "40px auto",
        padding: "24px",
        fontFamily: "system-ui, sans-serif",
      }}
    >
      <h1>VidyaPulse AI</h1>
      <p style={{ color: "#666" }}>Multimodal Lecture Intelligence Platform</p>
      <ul style={{ listStyle: "none", padding: 0, marginTop: "24px" }}>
        {pages.map((page) => (
          <li key={page.href} style={{ marginBottom: "12px" }}>
            <Link
              href={page.href}
              style={{ color: "#0070f3", fontWeight: 600 }}
            >
              {page.label}
            </Link>
            <span style={{ color: "#666" }}> · {page.note}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}
