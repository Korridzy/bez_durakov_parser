import { useCallback, useSyncExternalStore } from "react";

/** Desktop is the fallback for environments without matchMedia (including jsdom). */
export function useMediaQuery(query: string): boolean {
  const subscribe = useCallback((changed: () => void) => {
    if (typeof window.matchMedia !== "function") return () => {};
    const media = window.matchMedia(query);
    media.addEventListener("change", changed);
    return () => media.removeEventListener("change", changed);
  }, [query]);
  const snapshot = () =>
    typeof window.matchMedia === "function" && window.matchMedia(query).matches;
  return useSyncExternalStore(subscribe, snapshot, () => false);
}
