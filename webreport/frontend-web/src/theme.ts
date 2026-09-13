import { useEffect, useState } from "react";

export const accentPresets = [
  { name: "Коралл", color: "#ed786b" },
  { name: "Василёк", color: "#4667d5" },
  { name: "Ирис", color: "#8056b5" },
  { name: "Лаванда", color: "#a18bc8" },
  { name: "Роза", color: "#ac4970" },
  { name: "Шалфей", color: "#6d8e7e" },
];
export const defaultAccent = accentPresets[0].color;
const validColor = (value: string) => /^#[\da-f]{6}$/i.test(value);
const rgb = (value: string) =>
  [1, 3, 5].map((i) => parseInt(value.slice(i, i + 2), 16));
const hex = (values: number[]) =>
  "#" + values.map((v) => Math.round(v).toString(16).padStart(2, "0")).join("");
const luminance = (values: number[]) =>
  values
    .map((v) => {
      const c = v / 255;
      return c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
    })
    .reduce((sum, c, i) => sum + c * [0.2126, 0.7152, 0.0722][i], 0);

export function applyAccent(color: string) {
  const original = rgb(validColor(color) ? color : defaultAccent);
  let accessible = [...original];
  // Keep white button labels readable even with a very light custom accent.
  while (1.05 / (luminance(accessible) + 0.05) < 4.6)
    accessible = accessible.map((v) => v * 0.94);
  const style = document.documentElement.style;
  style.setProperty("--accent", hex(original));
  style.setProperty("--accent-strong", hex(accessible));
  style.setProperty("--accent-ink", hex(accessible.map((v) => v * 0.55)));
  let dark = [45, 31, 49];
  const lightContrast = 1.05 / (luminance(original) + 0.05);
  // Mid-tone custom colors may need darker ink than the usual plum.
  while (
    lightContrast < 4.5 &&
    (luminance(original) + 0.05) / (luminance(dark) + 0.05) < 4.55
  )
    dark = dark.map((v) => v * 0.9);
  style.setProperty(
    "--accent-contrast",
    (luminance(original) + 0.05) / (luminance(dark) + 0.05) >= 4.5
      ? hex(dark)
      : "#ffffff",
  );
}

export function useMotion() {
  const read = () => {
    try {
      return localStorage.getItem("wr-motion") !== "off";
    } catch {
      return true;
    }
  };
  const [motion, setMotion] = useState(read);
  useEffect(() => {
    try {
      localStorage.setItem("wr-motion", motion ? "on" : "off");
    } catch {}
  }, [motion]);
  useEffect(() => {
    const sync = (event: StorageEvent) => {
      if (event.key === "wr-motion") setMotion(read());
    };
    window.addEventListener("storage", sync);
    return () => window.removeEventListener("storage", sync);
  }, []);
  return [motion, setMotion] as const;
}

export function readAccent() {
  try {
    const stored = localStorage.getItem("wr-accent") || "";
    return validColor(stored) ? stored.toLowerCase() : defaultAccent;
  } catch {
    return defaultAccent;
  }
}

export function useAccent() {
  const [accent, setAccent] = useState(readAccent);
  useEffect(() => {
    applyAccent(accent);
    try {
      localStorage.setItem("wr-accent", accent);
    } catch {}
  }, [accent]);
  useEffect(() => {
    const sync = (event: StorageEvent) => {
      if (event.key === "wr-accent") setAccent(readAccent());
    };
    window.addEventListener("storage", sync);
    return () => window.removeEventListener("storage", sync);
  }, []);
  return [
    accent,
    (value: string) => {
      if (validColor(value)) setAccent(value.toLowerCase());
    },
  ] as const;
}
