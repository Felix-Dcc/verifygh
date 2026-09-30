/**
 * Theme constants shared by the server layout and the client provider.
 *
 * A plain module on purpose (no "use client"): the root layout is a server
 * component and needs THEME_SCRIPT as a real string, not a client reference.
 */
export const THEME_STORAGE_KEY = "verifygh-theme";

/**
 * Runs in <head> before the page paints, so a dark-mode visitor never sees a
 * white flash. Tiny and dependency-free; any failure (storage blocked, old
 * browser) falls back to the light theme.
 */
export const THEME_SCRIPT = `(function(){try{var p=localStorage.getItem("${THEME_STORAGE_KEY}")||"system";var d=p==="dark"||(p==="system"&&window.matchMedia("(prefers-color-scheme: dark)").matches);var r=document.documentElement;if(d)r.classList.add("dark");r.style.colorScheme=d?"dark":"light";}catch(e){}})();`;
