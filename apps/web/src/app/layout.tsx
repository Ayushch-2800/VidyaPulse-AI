import "./globals.css";

export const metadata = {
  title: "VidyaPulse AI",
  description: "Multimodal Lecture Intelligence Platform",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body
        style={{
          margin: 0,
          fontFamily: "system-ui, -apple-system, sans-serif",
        }}
      >
        {children}
        <footer
          style={{
            padding: "16px 24px",
            fontSize: "12px",
            color: "#9CA3AF",
            textAlign: "center",
          }}
        >
          Build {process.env.NEXT_PUBLIC_BUILD_COMMIT} · served from{" "}
          {process.env.NEXT_PUBLIC_BUILD_DIR} · started{" "}
          {process.env.NEXT_PUBLIC_BUILD_TIME}
        </footer>
      </body>
    </html>
  );
}
