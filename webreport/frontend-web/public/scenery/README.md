# Airy Dig AI scenery

Generated with the built-in ImageGen tool on 2026-09-13 from the user-approved near-white Dig AI mockup. Each deliverable is a separate PNG with an alpha channel. No generated backdrop is baked into the interface gradient.

- `architecture-left.png`: left-edge arch, stairs and prism.
- `architecture-right.png`: right-edge prism and low ridge.
- `grass-corner.png`: taller corner clump.
- `grass-tuft.png`: small sparse tuft, reused with open gaps.
- `../mascot/hill.png`: grounded tropical mound beneath the live Three.js shovel.
- `../mascot/shovel-hill.png`: static fallback while WebGL loads or is unavailable.

Layout, edge anchoring, opacity, bottom fade and motion live in `src/Atmosphere.tsx` and `src/expedition.css`. Sprites ignore pointer input and are hidden from accessibility. Grass animation respects both the app motion setting and reduced motion. The 3D character retains its original materials and controls. Its shadow receiver follows the open clearing of the new mound.

## Generation prompts

### hill

Transparent background. A production game sprite: a small low grassy hill with an open oval central green clearing for a character to dig in, rich fresh green grass, small tropical leaves along the left and right perimeter, three rounded warm gray stones at the front and a thin sandy apron. Match the hill at bottom right of reference, without its shovel or flag. Grounded soft mound, no floating underside. Wide 2:1 image, orthographic view slightly from above. Isolated on transparent background, PNG cutout.

### grass-corner

Create ONE production PNG sprite with a GENUINELY TRANSPARENT ALPHA background, not an interface mockup. The attached image is the APPROVED final Dig AI interface: use only its specified decoration as the exact style, color and composition reference. Match it very closely rather than inventing a new design. No UI, text, labels, characters, shovel, flag, ground rectangle, backdrop, clouds, checkerboard drawing or opaque white background. Preserve soft antialiased alpha edges.
Redraw ONLY the natural green GRASS CLUSTER at the far lower LEFT corner of the approved screen. One small asymmetrical cluster of elegant curved grass blades, tallest near the left quarter, tapering toward the right into shorter blades. About 12–18 clear blades total, varied heights and natural graceful bends, cheerful fresh grass green with lighter spring-green sunlit faces, a few deeper green accents. Match the approved reference, not dusty sage or cyan. No flowers, no tropical broad leaves, no stones, no dirt mound; just grasses joined at a very fine subtle grassy ground contact which fades to transparent. Smooth stylized illustration with soft dimensional shading and crisp silhouette. No detailed lawn texture. Approximate silhouette 2:1 width to height. Full object contained with narrow transparent margins. One cluster ONLY. Intended to render at 120px wide at the bottom edge and sway subtly as one CSS sprite. Actual transparent alpha.

### grass-tuft

Create ONE production PNG sprite with a GENUINELY TRANSPARENT ALPHA background, not an interface mockup. The attached image is the APPROVED final Dig AI interface: use only its specified decoration as the exact style, color and composition reference. Match it very closely rather than inventing a new design. No UI, text, labels, characters, shovel, flag, ground rectangle, backdrop, clouds, checkerboard drawing or opaque white background. Preserve soft antialiased alpha edges.
Redraw ONLY ONE of the tiny sparse GRASS TUFTS along the bottom of the approved screen, between the left corner and the input box. One small low tuft, 7–10 slender gracefully curved blades, some left leaning and some right leaning, a modest asymmetrical crown. Fresh natural yellow-green and medium grass-green, same hue and stylized soft dimensional shading as the grasses in the reference. Do not make blue-green, gray or dusty. No stones, flowers, clover, dirt clump, ground plane or scenery. Finely tapered isolated silhouette, soft antialiasing. Approximate 2:1 horizontal silhouette, narrow transparent margins. This is a small repeatable individual grass tuft to be placed with empty gaps around it, not a grass strip. Actual transparent alpha.

### architecture-left

On a solid pure white background, reproduce only the minimalist pale porcelain arch, short staircase and slender tall geometric prism at the lower LEFT of the reference chat. Pale icy-blue shadow faces, warm white lit faces, clean simple shapes, airy 3D miniature. No grass or interface. Portrait 4:5. A single isolated architectural group, plain white surrounding canvas, no background pattern. Soft ground fades to pure white.

Final background extraction (white illustration used as the edit target):

Transparent background. Remove the white surrounding background from this architectural illustration. Preserve the pale blue and ivory shapes, composition, soft shading and fine silhouette. Deliver a transparent PNG cutout.

### architecture-right

On a solid pure white background, reproduce only the tall minimalist pale porcelain prism and tiny warm white arch on a gently curved low ridge at the far RIGHT of the reference chat. Pale icy-blue shadow faces, warm white lit faces, clean simple shapes, airy 3D miniature. No grass or interface. Portrait 4:5. Group positioned at right edge. Plain pure white surrounding canvas, no background pattern, ground fades to pure white.

Final background extraction (white illustration used as the edit target):

Transparent background. Remove the white surrounding background from this architectural illustration. Preserve the pale blue and ivory shapes, composition, soft shading and fine silhouette. Deliver a transparent PNG cutout.

### shovel-hill (static fallback)

Transparent background. Isolated 3D game mascot sprite, matching EXACTLY the shovel and grassy mound at the bottom RIGHT of reference. Silver lavender cartoon shovel with big white eyes and purple irises, friendly smile, very short wooden shaft, orange-coral T-handle and coral flag at right. Small low grassy hill, vibrant fresh green lawn and tropical edge leaves, a few warm gray stones and sandy apron. Grounded mound, no floating rocky underside. Entire character and ground centered, square image, clean silhouette, transparent PNG cutout. No interface, letters or scenery.
