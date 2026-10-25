/**
 * The moving backdrop behind every page: drifting aurora light, a slowly scrolling
 * grid, twinkling stars and the odd light beam. Pure CSS (transform and opacity only,
 * so it stays on the compositor); it holds still for prefers-reduced-motion.
 */
export default function AnimatedBackground() {
  return (
    <div className="vp-bg" aria-hidden="true">
      <div className="vp-bg__aurora vp-bg__aurora--violet" />
      <div className="vp-bg__aurora vp-bg__aurora--pink" />
      <div className="vp-bg__aurora vp-bg__aurora--cyan" />
      <div className="vp-bg__aurora vp-bg__aurora--amber" />
      <div className="vp-bg__stars" />
      <div className="vp-bg__stars vp-bg__stars--far" />
      <div className="vp-bg__grid" />
      <span className="vp-bg__beam" />
      <span className="vp-bg__beam" />
      <span className="vp-bg__beam" />
    </div>
  );
}
