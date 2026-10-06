import { act, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ThinkingMark } from "./ThinkingMark";

type ChangeListener = (event: MediaQueryListEvent) => void;

function installMatchMedia(matches: boolean) {
  const listeners = new Set<ChangeListener>();
  const list = {
    matches,
    media: "(prefers-reduced-motion: reduce)",
    addEventListener: (_type: string, listener: ChangeListener) => {
      listeners.add(listener);
    },
    removeEventListener: (_type: string, listener: ChangeListener) => {
      listeners.delete(listener);
    },
  };
  Object.defineProperty(window, "matchMedia", {
    configurable: true,
    writable: true,
    value: vi.fn(() => list),
  });
  return {
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

describe("ThinkingMark", () => {
  it.each([
    ["thinking", "Думаю…"],
    ["reading", "Читаю данные…"],
    ["cancelling", "Отменяю…"],
  ] as const)("renders the status text for phase %s", (phase, text) => {
    installMatchMedia(false);

    render(<ThinkingMark phase={phase} />);

    const status = screen.getByRole("status");
    expect(status).toHaveAttribute("aria-live", "polite");
    expect(status).toHaveTextContent(text);
  });

  it("applies is-animated when the user does not prefer reduced motion", () => {
    installMatchMedia(false);

    const { container } = render(<ThinkingMark phase="thinking" />);

    const mark = container.querySelector(".thinking-mark");
    expect(mark).not.toBeNull();
    expect(mark).toHaveClass("is-animated");
    expect(mark).toHaveAttribute("aria-hidden", "true");
  });

  it("omits is-animated when the user prefers reduced motion and keeps the text", () => {
    installMatchMedia(true);

    const { container } = render(<ThinkingMark phase="reading" />);

    const mark = container.querySelector(".thinking-mark");
    expect(mark).not.toBeNull();
    expect(mark).not.toHaveClass("is-animated");
    expect(screen.getByRole("status")).toHaveTextContent("Читаю данные…");
  });

  it("drops the animation class live when the preference changes", () => {
    const media = installMatchMedia(false);
    const { container } = render(<ThinkingMark phase="cancelling" />);
    expect(container.querySelector(".thinking-mark")).toHaveClass(
      "is-animated",
    );

    act(() => media.emit(true));

    expect(container.querySelector(".thinking-mark")).not.toHaveClass(
      "is-animated",
    );
  });

  it("renders a static mark without throwing when matchMedia is missing", () => {
    Reflect.deleteProperty(window, "matchMedia");

    const { container } = render(<ThinkingMark phase="thinking" />);

    expect(container.querySelector(".thinking-mark")).toHaveClass(
      "is-animated",
    );
    expect(screen.getByRole("status")).toHaveTextContent("Думаю…");
  });

  it("uses an inline SVG only (no bitmap surface, no raster image)", () => {
    installMatchMedia(false);

    const { container } = render(<ThinkingMark phase="thinking" />);

    expect(container.querySelector("svg.thinking-mark")).not.toBeNull();
    expect(container.querySelectorAll("svg")).toHaveLength(1);
    expect(container.querySelector("img")).toBeNull();
    expect(container.querySelector("script")).toBeNull();
  });
});
