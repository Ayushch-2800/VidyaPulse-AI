"use client";

/**
 * Wraps the feature cards and moves each card's glow to follow the pointer by setting
 * --mx and --my on the card under it. One listener for the whole grid.
 */
export default function SpotlightGroup({
  className,
  children,
}: {
  className?: string;
  children: React.ReactNode;
}) {
  const onPointerMove = (e: React.PointerEvent<HTMLDivElement>) => {
    const card = (e.target as HTMLElement).closest<HTMLElement>(".vp-feature");
    if (!card) return;
    const rect = card.getBoundingClientRect();
    card.style.setProperty("--mx", `${e.clientX - rect.left}px`);
    card.style.setProperty("--my", `${e.clientY - rect.top}px`);
  };

  return (
    <div className={className} onPointerMove={onPointerMove}>
      {children}
    </div>
  );
}
