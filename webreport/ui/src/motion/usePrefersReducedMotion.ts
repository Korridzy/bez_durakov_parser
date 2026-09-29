import { useSyncExternalStore } from "react";

export const REDUCED_MOTION_QUERY = "(prefers-reduced-motion: reduce)";

function queryList(): MediaQueryList | null {
  // Old jsdom builds and some embedded browsers ship no matchMedia: treat that
  // as "no preference" instead of throwing.
  if (typeof window === "undefined" || typeof window.matchMedia !== "function") {
    return null;
  }
  return window.matchMedia(REDUCED_MOTION_QUERY);
}

function subscribe(onChange: () => void): () => void {
  const list = queryList();
  if (list === null) {
    return () => {};
  }
  list.addEventListener("change", onChange);
  return () => list.removeEventListener("change", onChange);
}

function getSnapshot(): boolean {
  return queryList()?.matches ?? false;
}

function getServerSnapshot(): boolean {
  return false;
}

/**
 * True while the user agent reports `prefers-reduced-motion: reduce`.
 * Re-renders on the media query's `change` event; the listener is removed on
 * unmount.
 */
export function usePrefersReducedMotion(): boolean {
  return useSyncExternalStore(subscribe, getSnapshot, getServerSnapshot);
}
