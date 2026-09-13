import { readFile, writeFile } from "node:fs/promises";

const layout = JSON.parse(
  await readFile(new URL("../src/brand-layout.json", import.meta.url), "utf8"),
);
const images = new Map();
for (const { asset } of layout.layers) {
  if (!images.has(asset)) {
    images.set(
      asset,
      (
        await readFile(new URL(`../public/brand/${asset}`, import.meta.url))
      ).toString("base64"),
    );
  }
}
// Favicons cannot fetch external SVG image references. Embed each unchanged
// transparent sprite; their transforms still come from the editable layout.
const assets = [...images.keys()];
const definitions = assets
  .map(
    (asset, index) =>
      `    <image id="asset-${index}" width="1" height="1" href="data:image/png;base64,${images.get(asset)}"/>`,
  )
  .join("\n");
const layers = layout.layers
  .map(
    ({ id, asset, x, y, size }) =>
      `  <use id="${id}" href="#asset-${assets.indexOf(asset)}" transform="translate(${x} ${y}) scale(${size})"/>`,
  )
  .join("\n");
await writeFile(
  new URL("../public/brand/dig-mark.svg", import.meta.url),
  `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${layout.canvas} ${layout.canvas}">\n  <defs>\n${definitions}\n  </defs>\n${layers}\n</svg>\n`,
);
