// Colours come from the design tokens in globals.css, so the same components read well
// on the dark workspace and, through .vp-paper, on the white PDF export.
export const panelStyle: React.CSSProperties = {
  padding: "20px",
  border: "1px solid var(--vp-border)",
  borderRadius: "18px",
  backgroundColor: "var(--vp-surface)",
  color: "var(--vp-text)",
  boxShadow: "var(--vp-shadow)",
};

export const itemStyle: React.CSSProperties = {
  padding: "14px 16px",
  border: "1px solid var(--vp-border)",
  borderRadius: "14px",
  backgroundColor: "var(--vp-surface-2)",
  color: "var(--vp-text)",
};

export const primaryButton: React.CSSProperties = {
  padding: "9px 18px",
  background: "var(--vp-gradient-btn)",
  color: "#fff",
  border: "none",
  borderRadius: "10px",
  fontWeight: 600,
  cursor: "pointer",
  boxShadow: "var(--vp-glow)",
};

export const secondaryButton: React.CSSProperties = {
  padding: "4px 12px",
  backgroundColor: "transparent",
  color: "var(--vp-violet-soft)",
  border: "1px solid var(--vp-border-strong)",
  borderRadius: "8px",
  fontSize: "0.85em",
  fontWeight: 500,
  cursor: "pointer",
};

export const mutedText: React.CSSProperties = { color: "var(--vp-muted)" };
export const errorText: React.CSSProperties = { color: "var(--vp-danger)" };

export const chipStyle: React.CSSProperties = {
  display: "inline-block",
  padding: "2px 9px",
  borderRadius: "999px",
  backgroundColor: "var(--vp-chip-bg)",
  color: "var(--vp-chip-text)",
  fontSize: "0.8em",
  fontWeight: 500,
};

export const fieldStyle: React.CSSProperties = {
  width: "100%",
  padding: "10px 12px",
  borderRadius: "10px",
  border: "1px solid var(--vp-border-strong)",
  backgroundColor: "var(--vp-field-bg)",
  color: "var(--vp-text)",
  boxSizing: "border-box",
  font: "inherit",
};
