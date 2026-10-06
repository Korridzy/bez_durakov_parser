import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

const styles = readFileSync("src/styles.css", "utf8");

const tokens = new Map(
  [...styles.matchAll(/(--color-[\w-]+):\s*([^;]+);/g)].map(
    ([, name, value]) => [name ?? "", value?.trim() ?? ""] as const,
  ),
);

function color(name: string): string {
  const value = tokens.get(name);
  if (value === undefined) throw new Error(`Missing colour token: ${name}`);
  const alias = /^var\((--color-[\w-]+)\)$/.exec(value);
  if (alias?.[1] !== undefined) return color(alias[1]);
  expect(value, name).toMatch(/^#[\da-f]{6}$/i);
  return value;
}

function luminance(hex: string): number {
  return [0.2126, 0.7152, 0.0722].reduce((sum, weight, index) => {
    const channel = parseInt(hex.slice(1 + index * 2, 3 + index * 2), 16) / 255;
    const linear = channel <= 0.04045 ? channel / 12.92 : ((channel + 0.055) / 1.055) ** 2.4;
    return sum + weight * linear;
  }, 0);
}

// Actual text surfaces, including hover/selected rows, card metadata, parameters,
// chart labels, reasoning, placeholders, hints, notices and enabled controls.
// The light palette is shared by both motion preferences; there is no dark theme.
const neutralSurfaces = [
  "--color-bg", "--color-surface", "--color-surface-raised",
  "--color-surface-muted", "--color-accent-soft",
] as const;
const pairs = [
  ...["--color-text", "--color-text-muted", "--color-text-faint", "--color-accent",
    "--color-accent-strong"].flatMap((text) => neutralSurfaces.map((surface) => [text, surface] as const)),
  ...["--color-bg", "--color-surface", "--color-surface-raised", "--color-surface-muted",
    "--color-warning-soft"].map((surface) => ["--color-warning", surface] as const),
  ...["--color-surface", "--color-surface-muted", "--color-danger-soft"].map(
    (surface) => ["--color-danger", surface] as const,
  ),
  ...["--color-accent", "--color-accent-strong", "--color-danger"].map(
    (surface) => ["--color-accent-contrast", surface] as const,
  ),
  ["--color-success", "--color-success-soft"],
  ["--color-info", "--color-info-soft"],
] as const;

describe("informative text contrast", () => {
  it.each(pairs)("%s on %s meets WCAG AA for small text", (text, surface) => {
    const foreground = luminance(color(text));
    const background = luminance(color(surface));
    const ratio = (Math.max(foreground, background) + 0.05) / (Math.min(foreground, background) + 0.05);
    const label = `${text} ${color(text)} on ${surface} ${color(surface)}: ${ratio.toFixed(4)}:1`;
    console.info(label);
    expect(ratio, label).toBeGreaterThanOrEqual(4.5);
  });
});

describe("table focus outline contrast", () => {
  it.each(["--color-bg", "--color-surface-raised"])("is at least 3:1 against %s", (surface) => {
    const outline = luminance(color("--color-focus"));
    const background = luminance(color(surface));
    const ratio = (Math.max(outline, background) + 0.05) / (Math.min(outline, background) + 0.05);
    const label = `--color-focus ${color("--color-focus")} on ${surface}: ${ratio.toFixed(4)}:1`;
    console.info(label);
    expect(ratio, label).toBeGreaterThanOrEqual(3);
  });
});
