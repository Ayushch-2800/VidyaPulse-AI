// Every light card sets its own text colour: in dark mode the page's text is near-white,
// and text that inherits it disappears on a white card.
export const panelStyle: React.CSSProperties = {
  padding: "16px",
  border: "1px solid #E5E7EB",
  borderRadius: "8px",
  backgroundColor: "#fff",
  color: "#111827",
};

export const itemStyle: React.CSSProperties = {
  padding: "12px 14px",
  border: "1px solid #E5E7EB",
  borderRadius: "8px",
  backgroundColor: "#F9FAFB",
  color: "#111827",
};

export const primaryButton: React.CSSProperties = {
  padding: "8px 16px",
  backgroundColor: "#0070f3",
  color: "#fff",
  border: "none",
  borderRadius: "6px",
  cursor: "pointer",
};

export const secondaryButton: React.CSSProperties = {
  padding: "4px 10px",
  backgroundColor: "#fff",
  color: "#0070f3",
  border: "1px solid #0070f3",
  borderRadius: "6px",
  fontSize: "0.85em",
  cursor: "pointer",
};

export const mutedText: React.CSSProperties = { color: "#6B7280" };
export const errorText: React.CSSProperties = { color: "#B91C1C" };

export const chipStyle: React.CSSProperties = {
  display: "inline-block",
  padding: "2px 8px",
  borderRadius: "999px",
  backgroundColor: "#EEF2FF",
  color: "#3730A3",
  fontSize: "0.8em",
};

export const fieldStyle: React.CSSProperties = {
  width: "100%",
  padding: "8px 10px",
  borderRadius: "6px",
  border: "1px solid #D1D5DB",
  backgroundColor: "#fff",
  color: "#111827",
  boxSizing: "border-box",
  font: "inherit",
};
