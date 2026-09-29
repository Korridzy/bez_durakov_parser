import { act, renderHook } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { usePrefersReducedMotion } from "./usePrefersReducedMotion";

type ChangeListener = (event: MediaQueryListEvent) => void;

function installMatchMedia(matches: boolean) {
  const listeners = new Set<ChangeListener>();
  const list = {
    matches,
    media: "(prefers-reduced-motion: reduce)",
    addEventListener: vi.fn((_type: string, listener: ChangeListener) => {
      listeners.add(listener);
    }),
    removeEventListener: vi.fn((_type: string, listener: ChangeListener) => {
      listeners.delete(listener);
    }),
  };
  const matchMedia = vi.fn(() => list);
  Object.defineProperty(window, "matchMedia", {
    configurable: true,
    writable: true,
    value: matchMedia,
  });
  return {
    matchMedia,
    list,
    listeners,
    emit(next: boolean) {
      list.matches = next;
      for (const listener of listeners) {
        listener({ matches: next } as MediaQueryListEvent);
      }
    },
  };
}

afterEach(() => {
  Reflect.deleteProperty(window, "matchMedia");
});

describe("usePrefersReducedMotion", () => {
  it("returns false without throwing when matchMedia is undefined (old jsdom)", () => {
    Reflect.deleteProperty(window, "matchMedia");
    expect(typeof window.matchMedia).toBe("undefined");

    const { result } = renderHook(() => usePrefersReducedMotion());

    expect(result.current).toBe(false);
  });

  it("reads the initial preference from the media query", () => {
    const media = installMatchMedia(true);

    const { result } = renderHook(() => usePrefersReducedMotion());

    expect(result.current).toBe(true);
    expect(media.matchMedia).toHaveBeenCalledWith(
      "(prefers-reduced-motion: reduce)",
    );
  });

  it("flips the value when the media query emits a change event", () => {
    const media = installMatchMedia(false);
    const { result } = renderHook(() => usePrefersReducedMotion());
    expect(result.current).toBe(false);

    act(() => media.emit(true));
    expect(result.current).toBe(true);

    act(() => media.emit(false));
    expect(result.current).toBe(false);
  });

  it("subscribes with addEventListener('change') and removes the listener on unmount", () => {
    const media = installMatchMedia(false);
    const { unmount } = renderHook(() => usePrefersReducedMotion());

    expect(media.list.addEventListener).toHaveBeenCalledWith(
      "change",
      expect.any(Function),
    );
    expect(media.listeners.size).toBe(1);

    unmount();

    expect(media.list.removeEventListener).toHaveBeenCalledWith(
      "change",
      expect.any(Function),
    );
    expect(media.listeners.size).toBe(0);
  });
});
