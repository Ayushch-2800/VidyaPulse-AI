// Shared by the generated app icon and social preview image (next/og renders these)

export const BRAND_GRADIENT =
  "linear-gradient(135deg, #7c3aed 0%, #db2777 55%, #f59e0b 100%)";

/** The pulse-line mark as an <svg> next/og can draw. */
export function PulseMark({ size }: { size: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 48 48">
      <path
        d="M8 25h7l3-7 6 16 6-22 3 13h7"
        fill="none"
        stroke="#fff"
        strokeWidth="3.6"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}
