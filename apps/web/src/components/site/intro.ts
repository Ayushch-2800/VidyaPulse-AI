/** sessionStorage key set once the intro has played, so it shows once per visit. */
export const INTRO_SEEN_KEY = "vp-intro-seen";

/**
 * Runs in <head> before the page paints: hides the intro straight away when it has
 * already played in this tab, so returning visitors never see it flash.
 */
export const INTRO_HEAD_SCRIPT = `try{if(sessionStorage.getItem(${JSON.stringify(
  INTRO_SEEN_KEY,
)}))document.documentElement.dataset.intro="seen"}catch(e){}`;
