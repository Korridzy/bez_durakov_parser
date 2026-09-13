# Dig AI brand layers

The active website mark contains three independent SVG image elements in `src/BrandMark.tsx`: the coral shovel, the large violet sparkle and the small violet sparkle. The two stars reuse one transparent sprite. Both render in front of the shovel; their higher placement leaves its silhouette clear.

## Move or resize a part

Edit `src/brand-layout.json`. Coordinates use a 1000 × 1000 canvas: `x` moves right, `y` moves down and `size` sets the square image size. Array order sets the layer order. Each PNG has transparent padding, so these values describe the image box.

With Vite running, open `/tests/brand.html`: select a layer, drag it on the large preview or change its coordinates and size. The small preview shows the actual website size. “Скопировать расположение” copies the layout JSON; paste that into `src/brand-layout.json` to apply it to the product. The preview does not change workspace data or preferences.

`npm run build` runs `scripts/build-brand-icon.mjs` first, assembling `dig-mark.svg` for the favicon from the SAME layout. The generated SVG embeds the two unchanged PNGs and positions three named layers. Do not edit its embedded image data by hand.

## Transparent assets

- [shovel.png](shovel.png): shovel alone, 1254 × 1254, RGBA.
- [sparkle.png](sparkle.png): one violet sparkle, 1254 × 1254, RGBA; reused at two sizes.
- [dig-mark.svg](dig-mark.svg): generated composition used for the favicon.

Generated with the built-in ImageGen tool in edit/extraction mode on 2026-09-13. Alpha was checked before integration. The original `dig-icon.png` and previous combined `dig-icon-sparkles.png` are retained as references; the website no longer uses either flattened image.

## Shovel extraction prompt

Edit target: `dig-icon.png`.

Extract ONLY the coral shovel from this logo as a standalone transparent PNG cutout. Remove the tiny violet sparkle completely. Preserve the shovel exactly: same diagonal angle, rounded blade, shaft, open D-handle, warm coral glossy shading and silhouette. Keep its original position and size on the square canvas. The background and the hole inside the handle must be fully transparent. No stars, no other objects, no shadow outside the shovel.

## Sparkle extraction prompt

Edit target: `dig-icon-sparkles.png`.

Extract ONLY the LARGE violet four-point sparkle from this icon as a separate standalone transparent PNG cutout. No shovel, no small sparkle, no surrounding objects or external shadow. Preserve the large sparkle's soft rounded tips, elegantly concave sides, glossy violet material and highlights. Place this ONE sparkle alone at the center of a square canvas, filling 85 percent of its width and height with equal padding. Fully transparent background.
